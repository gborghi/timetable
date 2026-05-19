# Backend image -- multi-stage, non-root, production-capable.
#
# Stage 1 (`builder`): installs Python wheels into a private prefix so
# the runtime image stays slim (no build toolchain, no pip cache).
# Stage 2 (`runtime`): copies the prefix on top of python:3.11-slim,
# adds the app source, drops to a non-root user, and runs uvicorn.
#
# Build:
#   docker build -f webui/backend/Dockerfile -t pitantum-backend .
#
# Test build (single worker, no API key, dev defaults):
#   docker run --rm -p 8000:8000 pitantum-backend
#
# Production hint (gunicorn+uvicorn-worker, N workers, fail-fast on
# missing PITANTUM_API_KEY when PITANTUM_ENV=production):
#   docker run -p 8000:8000 \
#     -e PITANTUM_ENV=production \
#     -e PITANTUM_API_KEY=$(openssl rand -hex 32) \
#     -e PITANTUM_DB_URL=postgresql+psycopg://... \
#     pitantum-backend \
#     gunicorn webui.backend.main:app \
#       -k uvicorn.workers.UvicornWorker \
#       -w 4 -b 0.0.0.0:8000

ARG PYTHON_VERSION=3.11-slim

# ---------- Stage 1: builder ----------
FROM python:${PYTHON_VERSION} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Build deps required by a few wheels on slim (numpy occasionally
# falls back to source on platforms without a matching binary wheel).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

COPY webui/backend/requirements.txt ./requirements.txt

# Install into a private prefix that we'll copy into the runtime stage.
# `gunicorn` is included for production multi-worker deploys (see CMD
# override in the docstring at the top of this file); it stays in the
# image even when uvicorn is the default runner.
RUN pip install --prefix=/install -r requirements.txt \
 && pip install --prefix=/install 'gunicorn>=21.2,<24.0'


# ---------- Stage 2: runtime ----------
FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/webui:/app/engine:/app/schedule

# Non-root user. UID/GID 1000 is the conventional first-user default
# and works cleanly with bind-mounts owned by the host user.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

WORKDIR /app

# Copy the prebuilt wheels prefix from the builder stage.
COPY --from=builder /install /usr/local

# Application sources. Owned by the non-root user so the process can
# create data/ + logs/ paths if needed.
COPY --chown=app:app webui/backend /app/webui/backend
COPY --chown=app:app engine /app/engine
COPY --chown=app:app schedule /app/schedule

# webui/data is the SQLite + runs/snapshots dir. Mount a volume here
# in production; the placeholder ensures the path exists and is owned
# by `app` so the process can write into it.
RUN mkdir -p /app/webui/data && chown -R app:app /app/webui/data

# Healthcheck baked into the image so `docker run` (without compose)
# still surfaces health status. Compose-level healthchecks still work
# and override this one.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=10 \
  CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status == 200 else 1)" \
    || exit 1

USER app

EXPOSE 8000

# Default command: single-worker uvicorn (matches the legacy test image).
# Override in compose / `docker run ... <cmd>` for gunicorn+UvicornWorker
# in production.
CMD ["uvicorn", "webui.backend.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log"]
