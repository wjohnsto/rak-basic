FROM python:3.13-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
COPY temp/ temp/
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000
