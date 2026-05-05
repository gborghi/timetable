# Backend image for E2E test orchestration.
#
# - python:3.11-slim base.
# - Installs `webui/backend/requirements.txt`.
# - Adds `engine/` + `schedule/` to PYTHONPATH so the solver code
#   imports correctly (the scripts in `webui/backend/engine_io.py`
#   call `import cpsat_v2_timetable as cv2`, which lives in
#   `engine/`).
# - Runs uvicorn on port 8000 with a single worker (good enough
#   for E2E).
#
# Build:
#   docker build -f webui/backend/Dockerfile -t pitantum-backend .
# Run (standalone):
#   docker run -p 8000:8000 pitantum-backend
#
# In docker-compose.test.yml the build context is the repo root so
# the COPY lines below see the whole tree.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Pre-install deps in a layer that changes rarely.
COPY webui/backend/requirements.txt /app/webui/backend/requirements.txt
RUN pip install -r /app/webui/backend/requirements.txt

# Copy the parts of the repo the backend actually imports.
COPY webui/backend /app/webui/backend
COPY engine /app/engine
COPY schedule /app/schedule

ENV PYTHONPATH=/app/webui:/app/engine:/app/schedule

EXPOSE 8000

# uvicorn binds to 0.0.0.0 so the frontend container can reach it.
CMD ["uvicorn", "webui.backend.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log"]
