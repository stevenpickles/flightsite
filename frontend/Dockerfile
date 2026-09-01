# syntax=docker/dockerfile:1.7
#
# FlightSite frontend image: the Vite/React static build served by nginx,
# which also reverse-proxies /api (including WebSocket upgrade) to the
# backend container. See docs/ARCHITECTURE.md §2 (deployment topology) and
# docs/adr/0002-two-container-compose-topology.md.
#
# No architecture-specific steps: both stages' base images publish
# linux/amd64 and linux/arm64 manifests.

# ---------------------------------------------------------------------------
# Build stage: produce the static production build (frontend/dist).
# ---------------------------------------------------------------------------
FROM node:22.23.2-trixie-slim AS build

WORKDIR /build

# Install locked dependencies first so this layer is cached across
# source-only changes.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Runtime stage: nginx, unprivileged (non-root, listens on 8080).
# ---------------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:1.31.4-alpine AS runtime

# Patch base-image packages with published fixes (CVE-2026-66046: libexpat
# 2.8.3 DoS, fixed 2.8.4-r0) until the pinned nginx tag ships them.
USER root
RUN apk upgrade --no-cache libexpat
USER 101

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 8080

# The base image already runs as its non-root nginx user (uid 101) and
# listens on 8080 by default; both are preserved here (docs/SECURITY.md §7).
