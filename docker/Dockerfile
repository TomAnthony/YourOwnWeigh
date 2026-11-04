# YourOwnWeigh server image — one plain-HTTP listener, run behind your own
# reverse proxy. Usually built in CI and pulled from GHCR; to build locally,
# from the repo root:
#   docker build -f docker/Dockerfile -t yow:local .
#
# Runtime is just Node 24 + ws + Node built-ins (node:sqlite); no build step,
# types are stripped at run time. The server listens on plain HTTP; your reverse
# proxy terminates TLS and forwards to it (see README).
FROM node:24-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server ./server
COPY connectors ./connectors

# Run as the base image's unprivileged `node` user (uid 1000), never root
# (server/ts/local.ts says so, and it avoids root-owned files in the bind mount).
# The bind-mounted ./data on the host must be writable by uid 1000 — see README.
RUN mkdir -p /data && chown node:node /data
VOLUME /data
USER node

# One plain-HTTP listener. YOW_TRUST_PROXY=1 lets it bind 0.0.0.0 inside the
# container (no TLS here — the reverse proxy in front terminates it) and makes
# failed-login limits use the proxy's X-Forwarded-For. Publish the port to the
# host loopback only (see docker-compose.yml) so it is reachable just through
# the proxy.
ENV YOW_DB_PATH=/data/yow.sqlite3 \
    YOW_PORT=8080 \
    YOW_LISTEN_HOST=0.0.0.0 \
    YOW_TRUST_PROXY=1

EXPOSE 8080
CMD ["node", "--experimental-strip-types", "server/ts/local.ts"]
