# ADR-0017: Feeder status sources and the opt-in Docker socket

**Status:** Accepted (2026-09-26; owner decisions recorded in the SPEC §10, §67 and §79
amendments of the same date, implemented in slice 077, issue
[#215](https://github.com/stevenpickles/flightsite/issues/215).)

## Context

The owner's receiver does not only feed FlightSite. It streams to five networks —
FlightRadar24, ADS-B Exchange, FlightAware (piaware, with MLAT), OpenSky and
AeroDataBox — and a handful of sibling pages run beside FlightSite on the same host
(tar1090, graphs1090, SkyAware, the FR24 feeder UI). None of that was visible in
FlightSite. The request (2026-09-26) was one page showing every feed's status, a link to
each network and to its per-feeder stats page, gaps in feeding, connection statistics,
and links to the other locally hosted pages.

SPEC §79 lists *multi-receiver deployments* as a v1 non-goal. Monitoring the networks
**one** receiver feeds is a different thing — nothing is ingested from them — and the
owner admitted it explicitly (§79 amendment). SPEC §10 fixes seven primary sections; the
owner chose a sub-route under Receiver rather than an eighth (§10 amendment). SPEC §67
wants the health area to answer "is FlightSite healthy?"; feeder status joins it (§67
amendment).

The hard question is **where each feed's status can be read from**, because no two
feeders publish it the same way and some do not publish it at all.

### What the owner's host exposes (read-only survey of fermi, 2026-09-26)

| Source | Endpoint | Signals | Must redact |
|---|---|---|---|
| Receiver (ultrafeeder / readsb) | `:8080/data/status.json` (1 s), `/data/stats.json` | `now`, `uptime`, `aircraft_with_pos`, `aircraft_count_by_type.mlat`; `last1min.messages`, `local.signal/noise/samples_dropped`, `remote.bytes_out` (bytes to all connectors), `max_distance`, `gain_db` | `receiver.json` `lat`/`lon` |
| ADSBx / AeroDataBox MLAT | `:8080/mlat-client-stats/<host>:31090.json` (~15 s) | `now`, `peer_count` (>0 up; AeroDataBox flaps 0↔1), `good_sync_percentage_last_hour`, `bad_sync_timeout`, `outlier_percent`, `last_bad_sync` (-1 never) | none |
| ADSBx / AeroDataBox ADS-B out | **ultrafeeder logs only**: `BeastReduce TCP output: Connection established` / `Remote server disconnected … <host> port 30004` (transitions only) | connected iff the last line for the host is "established" | never read `/run/adsbexchange-stats/*.json` (UUID) |
| FlightAware | `:8081/status.json` (`interval` 5000, `expiry` ms) | `piaware`/`adept`/`mlat`/`radio` = `{status: green\|amber\|red, message}`, `piaware_version`, `cpu_temp_celcius`, `system_uptime` | `site_url` (user + site) — usable only as the stats link |
| FlightRadar24 | `:8754/monitor.json` (every value a string) | `feed_status`, `feed_status_message`, `feed_current_server`, `feed_last_ac_sent_time`/`_num`, `feed_last_connected_time`, `rx_connected`, `num_messages`, `timing_source`, `time_update_utc`, `build_version` | `fr24key`, `feed_alias`, `feed_legacy_id`, `local_ips`; never link `/settings.html` |
| OpenSky | **logs only**, a Statistics block every 10 min | `currently online\|offline`, `N [P%] seconds online (overall)`, `disconnections`, `bytes sent (rate)` | timestamps are local time |

The local pages all answer on the LAN (and through the owner's reverse proxy). piaware's
`status.json` is served at `:8081/status.json`, **outside** the `/skyaware/` path a
reverse proxy usually exposes. FR24 runs with `MLAT=no` deliberately. There is no
AeroDataBox container: ADSBx and AeroDataBox are both connectors inside ultrafeeder.

Two facts shape the decision. First, three of the five networks publish a usable HTTP
status document on the LAN and two do not — for OpenSky and for ADS-B out on the
ultrafeeder connectors, the **only** source is the container's log. Second, several
documents carry identities (a feeder key, a UUID, a user and site id, the receiver's
coordinates) that must never leave the backend.

### Options considered for the log-only feeds

| Option | Verdict |
|---|---|
| Mount the Docker Engine socket and read container logs / health over its HTTP API | **Chosen, opt-in** |
| Have the owner mount each feeder's log directory into FlightSite | Rejected: most of these images log to stdout only; there is no file to mount |
| Scrape each network's public website (e.g. adsbexchange.com/myip) | Rejected: sends the owner's identity off the LAN on a timer, fragile, and out of scope (roadmap slice 077) |
| Report those feeds as permanently unknown | Kept as the **default**: it is what an install without the socket shows |

## Decision

1. **HTTP status documents first.** Each feed is an entry in `feeders.entries` with a
   `kind`; the `readsb`, `piaware`, `fr24` and `ultrafeeder` (MLAT) kinds poll the
   status document the feeder already publishes, over the LAN, on `poll_interval_s`
   (default 15 s). One vendor module per kind is the only code that knows that vendor's
   vocabulary, and it redacts the fields in the table above at parse time — they never
   reach the model, the database, the API or the logs.
2. **The Docker socket is opt-in and off by default.** `feeders.docker_socket` names the
   socket path; only when it is set does FlightSite read container logs
   (`opensky_logs`, ultrafeeder ADS-B out) or container health (`docker_health`). It
   talks to the Engine API directly with `httpx` over the unix socket — two read
   endpoints, `GET /containers/{name}/json` and `GET /containers/{name}/logs` — and uses
   no Docker SDK. Without the socket those signals read observability `none` and state
   `unknown`, **never `down`**: FlightSite being unable to see a feed is not the feed
   failing.
3. **Stats URLs are owner-supplied secrets behind an internal redirect.** Per-network
   stats pages are addressed by identities (a FlightAware user and site id, an FR24
   sharing key, a UUID). FlightSite never builds such a URL; the owner pastes the full
   URL into `secrets.yaml` as `feeders.stats_urls.<name>`, typed `SecretStr`, masked
   everywhere secrets are masked. The page links to
   `GET /api/internal/feeders/{name}/stats-link`, which answers `302` to the stored URL
   (or `404`); the URL never appears in `/api/v1`, the DOM or the logs. FlightAware's own
   `site_url` is used the same way as a fallback, and never exposed.
4. **Placement.** The page is `/receiver/feeders`, a lazy sub-route reached from
   Receiver and from Health — not an eighth sidebar section (SPEC §10 amendment).
   Diagnostics gains a counts-only `feeders` section; any feeder `down` degrades the
   overall status but never takes it down (SPEC §67 amendment). Outages become
   `feeder_offline` (high) and `feeder_restored` (info) activity events.
5. **History is FlightSite's own.** A per-feeder state machine with a two-poll debounce
   records outage episodes (90-day retention) and samples (14-day retention) in two new
   tables (migration 0017), written through the process's single writer on their own
   short transactions — ADR-0008's discipline unchanged.

## Consequences

- **The socket is a trust boundary, and crossing it is the owner's decision.** Access
  to the Docker Engine socket is root-equivalent on most hosts: anything that can talk
  to it can start a privileged container that mounts the host filesystem. A read-only
  bind mount (`:ro`) does not change that — it prevents replacing the socket file, not
  sending requests through it — and the `group_add` that lets the unprivileged backend
  user open it grants the same power to that user. FlightSite only ever issues the two
  read requests above, but the capability is the socket's, not FlightSite's.
  `docs/SECURITY.md` §10 says so plainly, the default is off, and every signal that
  needs the socket degrades to `unknown` without it.
- **Nothing new leaves the network.** Every poll is to a LAN address the owner
  configured; the socket is local. The outbound list in `docs/ARCHITECTURE.md` gains no
  internet destination. The stats links are opened by the owner's browser, not fetched
  by FlightSite.
- **A second kind of secret, and the first mapping of secrets.** The secret walker
  (`flightsite.config.secret_field_paths`) now discovers `dict[str, SecretStr]` fields,
  so masking, `secrets.yaml` write-back, the mask-means-unchanged rule and diagnostics
  redaction cover every stats URL without a parallel list.
- **Vendor formats will drift.** Each parser is isolated in its own module and tested
  against captured fixtures; a document that stops parsing is a failed poll
  (`feeder_poll_failures`, the `feeders` recent-error category), then `down` after the
  debounce — visible, not silent.
- **Reverse proxies.** The feeder `url`s are backend-side LAN addresses; the `web_url`s
  and local pages are browser-side links and may be proxy URLs. The two are configured
  separately for exactly that reason.
- **Demo mode** ships scripted probes for every kind (with a recurring FR24 outage) so
  the page, the timeline and the activity events have something to show with no feeder
  on the network; it never touches the socket.
