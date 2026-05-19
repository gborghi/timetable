# Frontend image -- multi-stage with two target stages:
#
#   * `dev`  (default for docker-compose.test.yml) -- runs `vite dev` so
#            E2E tests get HMR + the proxy behaviour they rely on.
#   * `prod` -- builds a static bundle (`vite build`) and serves it via
#            nginx. Use this target in real deployments.
#
# Build dev (default):
#   docker build -f webui/frontend/Dockerfile -t pitantum-frontend .
#
# Build prod static:
#   docker build -f webui/frontend/Dockerfile --target prod \
#       -t pitantum-frontend-prod .
#
# Run prod (the nginx config is baked in below; override BACKEND_URL
# at runtime to point at the API host):
#   docker run -p 8080:8080 \
#     -e BACKEND_URL=http://backend:8000 \
#     pitantum-frontend-prod

ARG NODE_VERSION=20-alpine

# ---------- Stage 1: deps ----------
FROM node:${NODE_VERSION} AS deps
WORKDIR /app
COPY webui/frontend/package.json webui/frontend/package-lock.json ./
# Prefer `npm ci` (lockfile-honouring, reproducible). Fall back to
# `npm install` only if the lockfile is missing -- a missing lockfile
# is a sign the host npm wrote a version the container's npm can't
# match, and CI should fix that, not paper over it.
RUN if [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        echo "warning: no package-lock.json -- using `npm install`" >&2; \
        npm install --no-audit --no-fund; \
    fi


# ---------- Stage 2: dev (vite dev server, used by E2E) ----------
FROM node:${NODE_VERSION} AS dev
WORKDIR /app

# Non-root: node images ship a `node` user (uid 1000); use it.
RUN mkdir -p /app && chown node:node /app
USER node

COPY --from=deps --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node webui/frontend ./

EXPOSE 5173

CMD ["npx", "vite", "dev", "--host", "0.0.0.0", "--port", "5173", \
     "--strictPort"]


# ---------- Stage 3: builder (vite build -> static dist) ----------
FROM node:${NODE_VERSION} AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY webui/frontend ./
RUN npm run build


# ---------- Stage 4: prod (nginx serving the static bundle) ----------
FROM nginx:1.27-alpine AS prod

# Production nginx config: serve the SvelteKit static export and proxy
# `/api/*` (and the SSE log streams) to the backend. BACKEND_URL is
# resolved at container start via envsubst.
COPY <<'EOF' /etc/nginx/templates/default.conf.template
server {
  listen 8080;
  server_name _;

  # Static SvelteKit build output.
  root   /usr/share/nginx/html;
  index  index.html;

  # Long-cache hashed assets, short-cache the HTML entry.
  location /_app/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
    try_files $uri =404;
  }

  location = /index.html {
    add_header Cache-Control "no-store";
  }

  # API + SSE -> backend
  location /api/ {
    proxy_pass ${BACKEND_URL};
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE: disable buffering so log lines stream live.
    proxy_buffering off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
  }

  # SvelteKit static fallback.
  location / {
    try_files $uri $uri/ /index.html;
  }
}
EOF

# Sensible default; override at runtime.
ENV BACKEND_URL=http://backend:8000

# Static bundle (adapter-static writes to ./build).
COPY --from=builder /app/build /usr/share/nginx/html

# Don't run nginx master as root: the alpine image already has a
# `nginx` user, just need to make it the worker AND tell nginx to
# avoid the privileged port. Listening on 8080 (unprivileged) handles
# the latter; switch to nginx's official non-root entrypoint by
# overriding the user directive.
RUN sed -i 's/^user .*/user nginx;/' /etc/nginx/nginx.conf \
 && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
                        /etc/nginx/templates

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -q --spider http://127.0.0.1:8080/ || exit 1

# Built-in entrypoint runs envsubst on /etc/nginx/templates/*.template.
