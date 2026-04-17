(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const messageEl    = $("#message");
  const sendEl       = $("#send");
  const transcriptEl = $("#transcript");
  const emptyStateEl = $("#empty-state");
  const approvalBox  = $("#approval-box");
  const approvalText = $("#approval-text");
  const sessionPill  = $("#session-pill");
  const taskPill     = $("#task-pill");
  const statePill    = $("#state-pill");

  let activeTaskId    = null;
  let stream          = null;
  let poller          = null;
  let assistantBubble = null;
  let updatesEl       = null;
  let typingEl        = null;

  const sessionId =
    localStorage.getItem("rak-demo-session") || crypto.randomUUID();
  localStorage.setItem("rak-demo-session", sessionId);
  sessionPill.textContent = "Session: " + sessionId.slice(0, 8);

  /* --- State pill styling --- */

  const STATE_CLASSES = {
    idle:            "pill--idle",
    queued:          "pill--queued",
    running:         "pill--running",
    awaiting_input:  "pill--awaiting",
    done:            "pill--done",
    failed:          "pill--failed",
    cancelled:       "pill--failed",
  };

  function setState(value) {
    statePill.textContent = "State: " + value;
    statePill.className = "pill " + (STATE_CLASSES[value] || "");
  }

  /* --- Transcript helpers --- */

  function hideEmptyState() {
    if (emptyStateEl) emptyStateEl.style.display = "none";
  }

  function cloneTemplate(id) {
    const tpl = document.getElementById(id);
    return tpl.content.firstElementChild.cloneNode(true);
  }

  function appendBubble(role, text) {
    hideEmptyState();
    const el = cloneTemplate("tpl-bubble-" + role);
    el.textContent = text;
    transcriptEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function appendUpdate(text) {
    if (!updatesEl) {
      updatesEl = cloneTemplate("tpl-updates");
      transcriptEl.appendChild(updatesEl);
    }
    const li = document.createElement("li");
    li.textContent = text;
    updatesEl.appendChild(li);
    scrollToBottom();
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    });
  }

  function showTyping() {
    if (typingEl) return;
    hideEmptyState();
    typingEl = cloneTemplate("tpl-typing");
    transcriptEl.appendChild(typingEl);
    scrollToBottom();
  }

  function hideTyping() {
    if (typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  }

  /* --- Reset between runs --- */

  function resetRun() {
    approvalBox.classList.remove("visible");
    approvalText.textContent = "Waiting for approval.";
    assistantBubble = null;
    updatesEl = null;
    hideTyping();
    if (stream) { stream.close(); stream = null; }
    if (poller) { clearInterval(poller); poller = null; }
  }

  /* --- SSE stream --- */

  function openStream(taskId) {
    stream = new EventSource(
      "/tasks/" + taskId + "/stream?events=update,token,done,failed,cancelled"
    );

    stream.addEventListener("update", function (event) {
      const data = JSON.parse(event.data);
      if (data.message) appendUpdate(data.message);
    });

    stream.addEventListener("token", function (event) {
      const data = JSON.parse(event.data);
      hideTyping();
      if (!assistantBubble) {
        assistantBubble = appendBubble("assistant", "");
      }
      assistantBubble.textContent += data.message || "";
      scrollToBottom();
    });

    stream.addEventListener("done", function (event) {
      const data = JSON.parse(event.data);
      hideTyping();
      setState("done");
      if (data.result && data.result.response) {
        if (!assistantBubble) {
          assistantBubble = appendBubble("assistant", data.result.response);
        } else {
          assistantBubble.textContent = data.result.response;
        }
      }
      cleanup();
    });

    stream.addEventListener("failed", function (event) {
      const data = JSON.parse(event.data);
      hideTyping();
      setState("failed");
      appendBubble("assistant", data.error || "Task failed.");
      cleanup();
    });

    stream.addEventListener("cancelled", function () {
      hideTyping();
      setState("cancelled");
      appendBubble("system", "Task cancelled.");
      cleanup();
    });
  }

  function cleanup() {
    if (stream) { stream.close(); stream = null; }
    if (poller) { clearInterval(poller); poller = null; }
  }

  /* --- Polling for approval state --- */

  function startPolling(taskId) {
    poller = setInterval(async function () {
      try {
        const res = await fetch("/tasks/" + taskId);
        if (!res.ok) return;
        const task = await res.json();
        setState(task.status);

        if (task.status === "awaiting_input" && task.input_request) {
          approvalText.textContent = task.input_request.prompt;
          approvalBox.classList.add("visible");
          scrollToBottom();
        }

        if (["done", "failed", "cancelled"].includes(task.status)) {
          clearInterval(poller);
          poller = null;
        }
      } catch (_) {
        /* network blip -- keep polling */
      }
    }, 900);
  }

  /* --- Approval --- */

  async function submitApproval(confirm) {
    if (!activeTaskId) return;
    approvalBox.classList.remove("visible");
    try {
      await fetch("/tasks/" + activeTaskId + "/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response: { confirm: confirm } }),
      });
      setState("queued");
      appendUpdate(confirm ? "Approval submitted." : "Cancellation submitted.");
    } catch (_) {
      appendUpdate("Failed to submit approval.");
    }
  }

  /* --- Main send --- */

  async function runTask() {
    const message = messageEl.value.trim();
    if (!message) return;

    resetRun();
    appendBubble("user", message);
    updatesEl = cloneTemplate("tpl-updates");
    transcriptEl.appendChild(updatesEl);
    messageEl.value = "";
    autoResize();
    setState("queued");
    showTyping();

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message, session_id: sessionId }),
      });

      const data = await res.json();
      activeTaskId = data.task_id;
      taskPill.textContent = "Task: " + activeTaskId.slice(0, 8);

      openStream(activeTaskId);
      startPolling(activeTaskId);
    } catch (_) {
      hideTyping();
      setState("failed");
      appendBubble("assistant", "Network error. Could not reach the server.");
    }
  }

  /* --- Auto-resize textarea --- */

  function autoResize() {
    messageEl.style.height = "auto";
    messageEl.style.height = Math.min(messageEl.scrollHeight, 160) + "px";
  }

  /* --- Event listeners --- */

  sendEl.addEventListener("click", runTask);

  $("#approve").addEventListener("click", function () {
    submitApproval(true);
  });

  $("#reject").addEventListener("click", function () {
    submitApproval(false);
  });

  messageEl.addEventListener("input", autoResize);

  messageEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      runTask();
    }
  });

  document.querySelectorAll("[data-prompt]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      messageEl.value = btn.dataset.prompt;
      messageEl.focus();
      autoResize();
    });
  });
})();
