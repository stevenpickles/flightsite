# Slice 077 — Feeders page (v0.10.0)

## Context

The owner streams the receiver's data to five networks (FlightRadar24, ADS-B Exchange,
FlightAware/piaware with MLAT, OpenSky, AeroDataBox) and runs sibling pages beside
FlightSite (tar1090, graphs1090, SkyAware, the FR24 feeder UI). None of that is visible
in FlightSite. Request (2026-09-26): one page showing every feed's status, links to each
network and to its per-feeder stats page, gaps in feeding and connection statistics, plus
links to the other locally hosted pages. Ships as v0.10.0.

Decisions taken with the owner (2026-09-26): Docker-socket log access is **opt-in**
(`feeders.docker_socket`, default off); the page is a **`/receiver/feeders` sub-route**
reached from Receiver and Health (SPEC §10's seven sections unchanged); per-network
stats links are **full URLs the owner pastes into `secrets.yaml`**, never built from
identities and never shown.

## What fermi exposes (read-only survey, 2026-09-26)

| Source | Endpoint | Signals | Redact |
|---|---|---|---|
| Receiver (ultrafeeder/readsb) | `:8080/data/status.json` (1 s), `/data/stats.json` | `now`, `uptime`, `aircraft_with_pos`, `aircraft_count_by_type.mlat`; `last1min.messages`, `local.signal/noise/samples_dropped`, `remote.bytes_out` (bytes to all connectors), `max_distance`, `gain_db` | `receiver.json.lat/lon` |
| ADSBx / AeroDataBox MLAT | `:8080/mlat-client-stats/<host>:31090.json` (~15 s) | `now`, `peer_count` (>0 up; AeroDataBox flaps 0↔1), `good_sync_percentage_last_hour`, `bad_sync_timeout`, `outlier_percent`, `last_bad_sync` (-1 never) | none |
| ADSBx / AeroDataBox ADS-B out | ultrafeeder logs only: `BeastReduce TCP output: Connection established|Remote server disconnected … <host> port 30004` (transitions only) | connected iff last line for host is "established" | never read `/run/adsbexchange-stats/*.json` (UUID) |
| FlightAware | `:8081/status.json` (`interval` 5000, `expiry` ms) | `piaware/adept/mlat/radio` = `{status: green|amber|red, message}`, `piaware_version`, `cpu_temp_celcius`, `system_uptime` | `site_url` (user+site) — usable only as the stats link |
| FlightRadar24 | `:8754/monitor.json` (all strings) | `feed_status`, `feed_status_message`, `feed_current_server`, `feed_last_ac_sent_time/_num`, `feed_last_connected_time`, `rx_connected`, `num_messages`, `timing_source`, `time_update_utc`, `build_version` | `fr24key`, `feed_alias`, `feed_legacy_id`, `local_ips`; never link `/settings.html` |
| OpenSky | logs only, Statistics block every 10 min | `currently online|offline`, `N [P%] seconds online (overall)`, `disconnections`, `bytes sent (rate)` | timestamps local TZ |

Local pages (200 on fermi and via `adsb.lonpix.com`): tar1090 `:8080/`, `:8080/graphs1090/`,
SkyAware `:8081/`, FR24 `:8754/`. piaware status is at `:8081/status.json`, outside the
`/skyaware/` proxy path. FR24 runs `MLAT=no` deliberately. No `aerodatabox-feed` container
exists; ADSBx and AeroDataBox are ultrafeeder connectors.

## Design

### Config (`config.yaml` → `FeederSettings`, hot-applied on save)
```yaml
feeders:
  poll_interval_s: 15          # 5–120
  docker_socket: null          # e.g. /var/run/docker.sock; enables log/health kinds
  entries:                     # list; validated for shape; names unique slugs
    - { name: receiver,     label: Receiver (readsb),  kind: readsb,           url: http://host.docker.internal:8080/,  web_url: http://fermi.local:8080/ }
    - { name: flightaware,  label: FlightAware,        kind: piaware,          url: http://host.docker.internal:8081/status.json, web_url: http://fermi.local:8081/ }
    - { name: fr24,         label: FlightRadar24,      kind: fr24,             url: http://host.docker.internal:8754/monitor.json, web_url: http://fermi.local:8754/ }
    - { name: adsbx,        label: ADS-B Exchange,     kind: ultrafeeder,      url: http://host.docker.internal:8080/, host: feed.adsbexchange.com, mlat_port: 31090, beast_port: 30004, container: ultrafeeder }
    - { name: aerodatabox,  label: AeroDataBox,        kind: ultrafeeder,      url: http://host.docker.internal:8080/, host: feed.aerodatabox.com, mlat_port: 31090, beast_port: 30004, container: ultrafeeder }
    - { name: opensky,      label: OpenSky Network,    kind: opensky_logs,     container: opensky }
  local_pages:
    - { label: tar1090,    url: http://fermi.local:8080/ }
    - { label: graphs1090, url: http://fermi.local:8080/graphs1090/ }
    - { label: SkyAware,   url: http://fermi.local:8081/ }
    - { label: FR24 feeder, url: http://fermi.local:8754/ }
```
`secrets.yaml`: `feeders: { stats_urls: { flightaware: "https://…", fr24: "…", opensky: "…", adsbx: "…", aerodatabox: "…" } }` — `dict[str, SecretStr]`; extend `secret_field_paths` if it does not already walk dict values. FlightAware's `status.json.site_url` is used as a fallback when no stats URL is configured (never exposed).

Kinds: `readsb` (receiver uplink summary: bytes_out rate, messages, aircraft, mlat inbound, samples_dropped), `piaware`, `fr24`, `ultrafeeder` (MLAT via HTTP always; ADS-B-out via ultrafeeder logs when the socket is set), `opensky_logs` (socket only), `docker_health` (backstop, socket only), `link_only`. Without the socket, socket-only signals read `observability: "none"` and state `unknown`, never `down`.

### Backend package `backend/src/flightsite/feeders/`
`model.py` (FeederState = up|degraded|down|unknown; FeederStatus, FeederSample, FeederEpisode), `protocol.py` (FeederProbe Protocol: `async probe() -> ProbeResult`), one vendor module per kind (`piaware.py`, `fr24.py`, `ultrafeeder.py`, `readsb.py`, `opensky.py`) — the only places that know a vendor's vocabulary (grep-boundary test like `receiver_metrics/test_field_isolation.py`), `docker.py` (httpx over unix socket via `AsyncHTTPTransport(uds=…)`: `GET /containers/{name}/json` health, `GET /containers/{name}/logs?stdout=1&stderr=1&since=&tail=`; no docker SDK), `service.py` (copy `receiver_metrics/service.py`: injected `sleep`/`clock`/`client_factory`, `poll_once()`, per-feeder state machine with 2-poll debounce before `down`, episodes on transitions, 60 s sample buffer + flush on own writer transactions, 300 s maintenance: prune samples > 14 d, episodes > 90 d; `apply_settings()` hot-apply rebuilds probes; `report` property), `repository.py`.
Migration `rev_0017_feeders.py`: `feeder_episodes(feeder TEXT, started_ms INTEGER, ended_ms INTEGER NULL, state TEXT, PK(feeder, started_ms)) WITHOUT ROWID`; `feeder_samples(feeder TEXT, ts_ms INTEGER, state TEXT, metrics_json TEXT, PK(feeder, ts_ms)) WITHOUT ROWID`. Resumable DDL; measured on a populated DB (adds empty tables only).
Activity: `feeder_offline` (high) / `feeder_restored` (info) via a `feeder_health_events()` producer + `FeederEpisode` fact; dedupe keys.
Counters: `feeder_poll_failures`. Diagnostics: `feeders` section `{configured, up, degraded, down, unknown, docker_socket: "available"|"unset"|"unreachable"}`, degraded roll-up when any feeder is down. Diagnostics error category prefix `flightsite.feeders`.
Demo: `demo/feeders.py` probes (all kinds, one scripted 3-minute outage on fr24 every 20 min) when `demo_enabled()`.

### API (docs/API.md §3.12)
- `GET /api/v1/feeders` → `{generated_at, poll_interval_s, docker_socket, receiver: {…readsb metrics|null}, feeders: [{name, label, kind, state, observability: http|docker|none, since, last_polled_at, last_success_at, last_data_sent_at, message, mlat: {peers, good_sync_pct, bad_sync_timeout_s, last_bad_sync_at}|null, adsb_out: {connected, since}|null, detail: {kind-specific, redacted}, web_url, stats_link: bool}], local_pages: [{label, url}]}`.
- `GET /api/v1/feeders/{name}/history?window=24h|7d|30d` → `{episodes: [{state, started_at, ended_at}], samples: [{t, state, metrics}], availability_pct}`.
- `GET /api/internal/feeders/{name}/stats-link` → 302 to the secret URL (404 when none). The URL never enters `/api/v1`, logs or the DOM.
- Config: `feeders` section on `GET/PUT /api/internal/config`; hot-applied by `_apply_feeders` in `_apply_live_settings`.

### Frontend
- `lib/api/feeders.ts` (types mirror schemas; `FEEDERS_POLL_MS = 10_000`, history query per window).
- `features/feeders/FeedersPage.tsx` at `/receiver/feeders` (lazy): header + "Health" link; receiver uplink tiles; one `FeederCard` per entry (StatusPill, since/last-data-sent, MLAT chip, ADS-B-out chip, "Open" web link, "View stats on X" link to the internal redirect, message); `GapTimeline` (24 h/7 d/30 d bars from episodes, availability %); `FeederMetricsChart` (peers / bytes rate / positions per min via `EChart`); `LocalPagesCard`.
- Receiver page: `FeedersSummaryCard` (n up / n down, link). Health page: `FeedersHealthCard` from diagnostics.
- Settings: `FeedersSection` (poll interval, docker socket path with a note, entries table add/remove with kind-specific fields, local pages table, per-entry stats URL as password field masked like the API key; hot-apply, no restart badge).
- Activity: `describeActivityEvent` branches + filter chips for the two new types.
- e2e `12-feeders.spec.ts` (demo stand-ins), visual `06-feeders.visual.spec.ts`.

### Docs, SPEC, ADR
ADR-0017 "Feeder status sources and the opt-in Docker socket" (candidates table from the survey). SPEC dated notes: §10 (Feeders reached under Receiver, not an eighth section), §67 (feeder status joins system health), §79 (feeder monitoring admitted; distinct from multi-receiver). PRODUCT §4.15; CONFIGURATION `### feeders` + secrets; DATA_MODEL §6.6 + §12; ARCHITECTURE §3.2/§3.3/§3.5 + §10 outbound list; SECURITY §3/§10 (socket trust, stats URLs as secrets); INSTALL (socket mount + `group_add`, local endpoints via `host.docker.internal`, reverse-proxy note); API §3.12; ROADMAP v0.10.0 row.

## Work packages (agents in worktrees on `077-feeders-page`)
- **A (opus)** backend `feeders/` package, vendors, docker client, service, repository, migration 0017, API v1 + internal redirect, schemas/serializers, demo probes, tests, API/DATA_MODEL docs.
- **B (opus)** config model + secrets dict support + CONFIGURATION/example, `app.py` wiring + hot-apply, diagnostics section, activity events/producers, counters, error category, SPEC notes, ADR-0017, PRODUCT/ARCHITECTURE/SECURITY/INSTALL, compose socket comment, tests.
- **C (sonnet)** `lib/api/feeders.ts`, FeedersPage + components, route, Receiver summary card, Health card, tests, visual spec.
- **D (sonnet)** Settings section + config types/draft/validation, activity describe + filter chips, e2e spec.
Contracts above are fixed; agents report deviations rather than changing shapes.

## Verification
Backend: ruff/mypy/pytest (new `tests/feeders/`, migration test, app wiring negative test: no socket ⇒ no docker client; secrets test: stats URLs absent from `/api/v1/feeders`, diagnostics, logs). Frontend: lint/typecheck/vitest. E2E + visual on the demo stack. Pre-release: run the release backend image against fermi's backup (migration 0017), then on fermi configure entries + `docker_socket` and confirm all six rows read `up` with live numbers.
