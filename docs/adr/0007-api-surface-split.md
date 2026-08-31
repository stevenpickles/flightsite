# ADR-0007: Split API surface — documented read-only /api/v1 vs internal mutations

**Status:** Accepted (2026-08-31)

## Context

SPEC §74: the supported, documented external API is read-only in v1, but the frontend
needs mutations (config, rules, watchlists, metadata update, reset). Mixing both in
one namespace invites third-party dependence on endpoints we must remain free to
change, and complicates a future auth story.

## Decision

Two prefixes served by the same FastAPI app:

- **`/api/v1/…`** — the supported external contract: read-only REST resources
  (current aircraft, interesting aircraft, aircraft history, sightings, analytics,
  receiver statistics, activity, health) plus the live WebSocket
  (`/api/v1/ws/live`, snapshot-then-delta). Versioned, documented in `docs/API.md`,
  exposed via OpenAPI. Breaking changes require a version bump.
- **`/api/internal/…`** — everything mutating plus frontend-only conveniences.
  Unversioned, explicitly undocumented as external contract, marked unstable. Excluded
  from the published OpenAPI contract documentation.

Secrets never appear in responses on either surface (SPEC §29). Both surfaces are
unauthenticated in v1 (ADR-0010); the internal prefix gives a future auth layer a
one-line perimeter ("everything under /api/internal requires auth" plus write-methods
generally).

## Consequences

- Third parties get a stable read-only integration surface; we keep freedom to
  reshape frontend plumbing every release.
- The WebSocket carries live state only; internal state changes (e.g., rule edits)
  take effect via normal REST + query invalidation, keeping the WS protocol small.
- API contract tests (CI gate) target `/api/v1` exhaustively; `/api/internal` is
  covered by ordinary integration tests instead.
