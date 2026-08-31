# syntax=docker/dockerfile:1.7
#
# FlightSite backend image: FastAPI (uvicorn) + SQLite, packaged as a
# multi-stage build so the runtime image ships no compiler toolchain and no
# uv itself. See docs/ARCHITECTURE.md §2 (deployment topology) and
# docs/adr/0002-two-container-compose-topology.md for the container contract;
# docs/SECURITY.md §7 for the non-root requirement.
#
# No architecture-specific steps: both stages' base images publish
# linux/amd64 and linux/arm64 manifests, so this Dockerfile builds natively
# (or under QEMU emulation) for both without special-casing either.

# ---------------------------------------------------------------------------
# Build stage: resolve the locked dependency set and build the package into
# a self-contained virtualenv.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.12.8-python3.12-trixie-slim AS build

# UV_COMPILE_BYTECODE: pre-compile .pyc files so the runtime image starts
#   faster instead of compiling on first import.
# UV_LINK_MODE=copy: the venv this stage builds is copied (not bind-mounted)
#   into the runtime stage, so hardlinks into uv's cache would dangle.
# UV_PYTHON_DOWNLOADS=never: this image already ships the pinned Python 3.12
#   toolchain; never reach out to fetch another one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/flightsite/venv

WORKDIR /build

# Install locked dependencies first, without the project itself, so this
# layer is cached across source-only changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Now install the project itself. --no-editable: the runtime stage below
# copies only the venv, not /build/src, so an editable install (uv's
# default for a local project) would leave the venv pointing at source that
# no longer exists — install a real wheel into site-packages instead.
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---------------------------------------------------------------------------
# Runtime stage: minimal image, non-root, only the built venv + interpreter.
#
# Deliberately bookworm (Debian 12), not trixie like the build stage above:
# it is a fully supported release and, at the time of writing, free of the
# build stage's transient trixie-image OpenSSL advisory (Trivy-clean; the
# fix already exists upstream, just not yet baked into a published trixie
# image). This is safe to mix with the trixie build stage because nothing
# is compiled against either stage's system libraries here — `uv sync`
# installs prebuilt manylinux wheels, and only the resulting venv is copied
# across, so there is no glibc-ABI coupling between the two stages.
# ---------------------------------------------------------------------------
FROM python:3.14.7-slim-bookworm AS runtime

# Non-root, fixed-uid user (docs/SECURITY.md §7: both containers run as
# non-root on minimal base images). uid/gid 1000 is the conventional
# first-user id and matches common host bind-mount ownership expectations.
RUN groupadd --gid 1000 flightsite \
    && useradd --uid 1000 --gid flightsite --no-create-home --shell /usr/sbin/nologin flightsite

# FLIGHTSITE_DATA_DIR: the single bind-mount contract (docs/ARCHITECTURE.md
# §2.1 / docs/adr/0002) — config.yaml, secrets.yaml, the SQLite database,
# logs/, and backups/ all live under this one directory. It is created here
# with a placeholder so a first run without a bind mount still has somewhere
# writable; in production it is replaced by the host bind mount (compose.yaml).
ENV FLIGHTSITE_DATA_DIR=/opt/flightsite/data \
    PATH=/opt/flightsite/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=build --chown=flightsite:flightsite /opt/flightsite/venv /opt/flightsite/venv

RUN mkdir -p /opt/flightsite/data && chown flightsite:flightsite /opt/flightsite/data

WORKDIR /opt/flightsite
USER flightsite

EXPOSE 8000

# No curl/wget in the slim base: probe the health endpoint from the stdlib
# instead. A non-2xx status or any exception exits non-zero.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"]

CMD ["flightsite-serve"]
