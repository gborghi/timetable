# Frontend image for E2E test orchestration.
#
# Two-stage:
# 1. `deps`: install node_modules in a layer that survives source
#    changes.
# 2. `dev`: copy the source on top, run `vite dev --host 0.0.0.0`.
#    We use vite dev (not the production preview) because the dev
#    server proxies the API to the backend exactly the way a local
#    developer hits it.
#
# The frontend talks to the backend via VITE_BACKEND_URL (set in
# docker-compose.test.yml). Without that env var it defaults to
# http://127.0.0.1:8000 which only works on the host network.

FROM node:20-alpine AS deps
WORKDIR /app
COPY webui/frontend/package.json webui/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund


FROM node:20-alpine AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY webui/frontend ./

EXPOSE 5173

# vite dev binds to 0.0.0.0 + the strict-port flag so health checks
# on :5173 succeed deterministically.
CMD ["npx", "vite", "dev", "--host", "0.0.0.0", "--port", "5173", \
     "--strictPort"]
