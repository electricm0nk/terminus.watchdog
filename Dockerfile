# syntax=docker/dockerfile:1

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Install dependencies into a virtual environment
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY watchdog/ ./watchdog/
RUN uv sync --frozen --no-dev


# ── Stage 2: final ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source
COPY watchdog/ ./watchdog/

# Use the venv Python
ENV PATH="/app/.venv/bin:$PATH"

# Expose health/metrics port
EXPOSE 9090

CMD ["python", "-m", "watchdog.main"]
