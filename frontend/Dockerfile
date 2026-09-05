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

# Patch every base-image package that has a published fix until the pinned
# nginx tag ships them. Targeted upgrades (libexpat for CVE-2026-66046, then
# util-linux/libuuid for CVE-2026-53612..78408) kept lagging the Trivy gate
# by one advisory each, so this upgrades the whole Alpine package set: the
# image is rebuilt on every push and the scan in .github/workflows/docker.yml
# fails on any fixed HIGH/CRITICAL finding left behind (docs/SECURITY.md §7).
USER root
RUN apk upgrade --no-cache
USER 101

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 8080

# The base image already runs as its non-root nginx user (uid 101) and
# listens on 8080 by default; both are preserved here (docs/SECURITY.md §7).
