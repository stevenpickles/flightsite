# FlightSite Security Baseline

This document records FlightSite's security assumptions, controls, and known risk
areas (SPEC §87). It is updated whenever a slice changes a security-relevant behavior.

---

## 1. Threat Model and Deployment Assumption

**FlightSite v1 assumes a trusted-LAN deployment.** There is no built-in
authentication, authorization, or transport encryption in v1 (SPEC §75). Anyone who
can reach the FlightSite ports can read all data and change all settings, rules, and
watchlists.

What FlightSite does defend against, even on a trusted LAN:

- Malformed or malicious decoder output (untrusted network input parser)
- Accidental secret disclosure through logs, APIs, diagnostics, or backups
- Data corruption from power loss or unclean shutdown
- Vulnerable dependencies and container images (scanned, gated)

What it explicitly does not defend against in v1:

- A hostile actor on the same network
- Public-internet exposure

## 2. Public Exposure Is Unsupported

**Do not expose FlightSite directly to the public internet.** It is not supported
securely by default. If remote access is needed:

- Prefer a VPN (WireGuard/Tailscale-style) into the LAN, or
- Front FlightSite with a reverse proxy that terminates TLS and enforces
  authentication (e.g., basic auth, forward-auth/SSO).

Built-in or reverse-proxy-aware application authentication is future work
(roadmap backlog), not a v1 feature.

## 3. Secrets Handling

Canonical layout (SPEC §29):

- Non-secret configuration: `/opt/flightsite/data/config.yaml`
- Secrets: `/opt/flightsite/data/secrets.yaml` and/or `FLIGHTSITE_*` environment
  variable overrides. The only v1 secret is the optional AeroDataBox API key.

Enforced rules (tested, not aspirational — see slices 004, 019, 026, 042, 043):

- Secrets never appear in logs at any log level.
- Secrets never appear in any documented read-only API response.
- The Settings UI masks stored values; plaintext secrets are never round-tripped to
  the client.
- Diagnostics/support output provably contains no secrets (automated test).
- Backups include secrets only when explicitly requested, and the backup manifest
  states whether they are included.

## 4. Untrusted Input: Decoder Ingestion

The decoder endpoint is network input and is treated as untrusted, even on the LAN.
The ingestion adapter (slice 007) must survive, without crashing or corrupting state:
invalid JSON, missing/extra fields, absurd values (positions, altitudes, timestamps),
oversized payloads, and abrupt disconnects. Malformed-input handling is covered by
fuzz-style tests, and no decoder-specific assumption may leak past the adapter
boundary. The same posture applies to downloaded metadata files (slices 021–023):
downloads are validated before transactional import, and a failed or suspect import
leaves the previous dataset intact.

## 5. Browser Notifications

Notifications use the browser Notification API only (SPEC §48). Permission is
requested only after the user opts in (setup wizard or settings), never unprompted.
Notification content includes aircraft data only — never secrets or configuration.
Denied/blocked permission degrades cleanly and is surfaced in diagnostics.

Two consequences of that first rule, as implemented (slice 040):

- The request is issued from the user's own click — the wizard's **Finish** when the
  notification preference is on, or the **Allow notifications** button in Settings —
  and never from an arriving alert, a page load, or a background task. Firefox and
  Safari require that user activation anyway; FlightSite requires it of itself.
- Browsers withhold the Notification API entirely outside a secure context (HTTPS, or
  a `localhost`/`127.0.0.1` origin). Reaching FlightSite over plain HTTP on a LAN
  address — the normal deployment of §1 — therefore means no notifications at all.
  That is reported as its own state ("Unavailable on this address") rather than as a
  fault, and every other alert surface (map emphasis, interesting panel, activity
  feed) is unaffected. Alerts that could not be shown are counted and displayed
  alongside the permission, so a silently-degraded install is visibly degraded.

## 6. Data Integrity: SQLite, Power Loss

- WAL mode with recovery on startup; automatic integrity checks (`quick_check`) at
  startup and during scheduled maintenance.
- No assumption that shutdown hooks run; sighting recovery closes/repairs state left
  open by unclean shutdown (slice 053), with diagnostics on problems.
- Backups use SQLite-safe snapshotting (VACUUM INTO / backup API), are
  checksum-verified, and restores validate manifest checksums and schema
  compatibility before touching existing data (slice 043). Destructive restore and
  reset operations require explicit confirmation.

## 7. Container Boundaries

- Both containers run as non-root users on minimal base images.
- The backend's writable filesystem surface is the `/opt/flightsite/data` bind mount;
  everything else is immutable application content.
- No anonymous volumes hold important state (SPEC §6, §116).
- The frontend proxies API traffic to the backend; only intended ports are published.
- Images are scanned (Trivy) in CI; scan gates block releases on material findings.

## 8. Dependency and Supply-Chain Controls

CI-enforced from slice 003/006 (SPEC §88):

- `pip-audit` (Python) and `npm audit` (Node) dependency vulnerability scanning
- Trivy container image scanning
- gitleaks secret scanning on the repository
- License compatibility checks for dependencies and bundled data/assets
- Dependabot automated update PRs (pip, npm, GitHub Actions, Docker)

**Release-blocking rule:** material high/critical findings block releases. They may be
waived only with a documented justification (false positive or not exploitable in
FlightSite's deployment model) recorded in the release PR.

## 9. External API Expectations

The documented external API is read-only in v1 (SPEC §74). Mutation endpoints used by
the frontend (configuration, rules, watchlists) are internal, undocumented, and not a
compatibility surface — but they share the same trust model: no auth in v1, trusted
LAN only. Nothing in the read-only API exposes secrets or filesystem paths beyond the
documented data directory.

## 10. What Data Leaves Your Network

FlightSite is local-first. The complete list of optional outbound traffic:

| Traffic | When | What is sent |
|---|---|---|
| AeroDataBox route enrichment | Only when `enrichment.aerodatabox_enabled` is on **and** an API key is set; then at most once per airline callsign per `enrichment.route_ttl_days` (default 7 days), capped by `enrichment.daily_lookup_budget` lookups per UTC day when you set one, and by 10 requests/minute always | One `GET https://api.aerodatabox.com/flights/callsign/{callsign}` per lookup: the transmitted callsign in the URL path and your API key in the `X-Api-Key` header. No request body, no query parameters. |
| Basemap tiles | When using internet basemaps (default) | Standard tile HTTP requests, which reveal the viewed map area (and therefore approximately your receiver's region) to the tile provider |
| Metadata updates | Only on the manual "Update Aircraft Metadata" action | Plain HTTP(S) downloads from Mictronics/tar1090, FAA, airport-data and route-directory sources; nothing about your receiver is uploaded |
| Route directory download | Only on the manual "Update Aircraft Metadata" action | One `GET https://github.com/vradarserver/standing-data/archive/refs/heads/main.zip` — a ~7 MB public archive of Virtual Radar Server standing data (CC0). No headers of yours, no key, no query string, no body: the request says nothing except which file is wanted. Nothing is uploaded, and the file is read into the local `route_directory` table and discarded ([ADR-0016](adr/0016-offline-route-directory.md)). |

### The offline directory comes first, so most callsigns are never sent

Since slice 071 FlightSite imports a local route directory and consults it before
AeroDataBox ([ADR-0016](adr/0016-offline-route-directory.md)). A callsign the directory
knows is answered from your own database and **never leaves your network at all** — no
request is made, no credit is spent, and the route is labelled `vrs` rather than
`aerodatabox` wherever it is shown. AeroDataBox is asked only for the callsigns the
directory does not know, and only under the limits in the table above.

The directory's own download is the one new outbound request, and it is the least
revealing one here: a single unauthenticated GET for a public file, made only when you
press "Update Aircraft Metadata", carrying nothing about your receiver, your aircraft or
you. It is not scheduled and never happens on its own.

### What route enrichment does *not* send

Only callsigns in the ICAO airline-flight form (a three-letter designator plus a flight
number, e.g. `DAL1234`) are ever looked up. Blank callsigns, registrations flown as
callsigns (`N738AB`) and tactical callsigns are never sent. Nothing else about the
aircraft or the receiver leaves your network — not its ICAO 24-bit address, its
registration, its position, altitude or squawk, and not your receiver's location, site
name or identity. The request carries no body and no query string, so the callsign and
the key are the entire payload; the response is read and discarded except for the two
airport identifiers and the flight number, which are cached locally.

Answers are cached in the local `route_cache` table keyed by callsign, including "no
route found" (24 hours) and "legally restricted" (the same week as a route), so one
flight costs at most one request per `route_ttl_days` however many times it is seen — and
a route confirmed identical on three separate days is frozen for 30 days. If you set
`daily_lookup_budget`, no request at all is made once that many lookups have been spent
in a UTC day — and where an answer has expired that FlightSite cannot refresh, the
expired one is served for another day rather than a fresh request being forced. Turning
the feature off, or removing the key, stops every request: the provider is not
constructed at all, so no socket is opened.

Everything else — aircraft observations, sightings, analytics, alerts, configuration —
stays on your host. FlightSite has no telemetry, no phone-home, and no account system.
Core functionality works with all outbound traffic blocked (offline basemap
degradation is a tested path).

## 11. Reporting

Security issues in FlightSite may be reported via GitHub issues (or GitHub private
vulnerability reporting once enabled for the repository).
