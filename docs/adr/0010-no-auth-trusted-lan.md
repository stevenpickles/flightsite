# ADR-0010: No built-in authentication in v1 (trusted LAN)

**Status:** Accepted (2026-08-31)

## Context

FlightSite v1 targets homelab deployments on a private LAN (SPEC §75). Building
credible authentication (accounts, sessions/tokens, CSRF, password storage, lockouts)
is substantial scope with real security downside if done shallowly, while typical
users deploy behind their router alongside the decoder itself, or already run a
reverse-proxy auth layer (Authelia, Tailscale, VPN) for their whole lab.

## Decision

v1 ships **no built-in authentication or authorization**. The deployment assumption
is a trusted LAN. This is stated prominently in `docs/SECURITY.md` and the README:
exposing FlightSite directly to the public internet is **not supported securely by
default**.

Design keeps the future path clean rather than building it now:

- All mutating endpoints live under `/api/internal` (ADR-0007), a single perimeter a
  future auth layer can guard.
- Secrets never transit any API response (SPEC §29), so read access never leaks keys.
- The frontend container is the single origin, where reverse-proxy auth naturally
  attaches today for users who want it.

Adding application-level auth or first-class reverse-proxy integration later requires
a superseding ADR.

## Consequences

- Anyone with LAN network access can view data and change settings — accepted and
  documented for the v1 threat model; mitigations (VPN, proxy auth) documented in
  SECURITY.md.
- No auth code to test/maintain in v1; setup wizard stays frictionless.
- The read-only external API (SPEC §74) is likewise open on the LAN; consumers need
  no credentials.
- Security review of v1 concentrates on real v1 risks: malformed decoder input,
  supply chain, secret handling, SQLite integrity.
