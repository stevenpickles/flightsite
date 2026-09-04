# FlightSite Configuration Reference

Everything FlightSite can be configured with, where each setting lives, and which
settings need a restart.

Most people never edit a file: the setup wizard and the Settings page write the same
canonical configuration model this page documents. Editing YAML by hand is supported
and equivalent.

- [Where configuration lives](#where-configuration-lives)
- [Load order](#load-order)
- [Which settings need a restart](#which-settings-need-a-restart)
- [Configuration reference](#configuration-reference)
- [Secrets](#secrets)
- [Environment variables](#environment-variables)
- [Deployment variables](#deployment-variables-compose-only)

---

## Where configuration lives

All persistent state sits under one directory — `/opt/flightsite/data` by default,
bind-mounted into the backend container:

| Path | What it is |
|---|---|
| `config.yaml` | Non-secret configuration. Rewritten whenever you save from the UI |
| `secrets.yaml` | API keys only. Written `0600`, never returned by the API, never logged |
| `flightsite.sqlite3` (+ `-wal`, `-shm`) | The single SQLite database |
| `logs/` | Rotating JSON logs, when `log_file_enabled` is true |
| `backups/` | Default destination for `flightsite-backup` archives |

A complete, commented `config.yaml` carrying every default ships as
[`config.example.yaml`](../config.example.yaml) in the repository root.

**A missing `config.yaml` is a valid state, not an error.** Every key is optional and
falls back to its built-in default; the absence of the file is exactly what FlightSite
uses to detect a first run and show the setup wizard.

Saving from the UI rewrites `config.yaml` wholesale. The output is clean and stable,
but **comments are not preserved** — keep your own notes elsewhere if you hand-edit.

---

## Load order

Later sources win:

1. Built-in defaults
2. `config.yaml`
3. `secrets.yaml`
4. `FLIGHTSITE_*` environment variables

One consequence is worth knowing before you use environment overrides: **a value
pinned by an environment variable keeps winning after you change it in the UI.** The
save succeeds and is written to `config.yaml`, but the environment variable overrides
it again on the next load, so the setting appears to revert. Use environment
overrides for values you intend to freeze, and the UI for everything else.

Unknown keys are treated asymmetrically on purpose: a stray `FLIGHTSITE_*` variable is
ignored (the container's environment is not FlightSite's to police), but an
unrecognised key in `config.yaml`, `secrets.yaml`, or an API payload is rejected with
an error naming the keys it does know. A typo in a file is a mistake worth surfacing.

---

## Which settings need a restart

Most of FlightSite's runtime is assembled once, at backend startup. Saving a setting
always persists it immediately, but only some take effect in the running process.

Restart the backend with:

```bash
docker compose restart flightsite-backend
```

### Applies immediately

`display_radius_nm`, `map.*`, `notifications.*`, and `units` / `timezone` as far as
the browser's own rendering is concerned. Alert **rules** and **watchlists** edited on
the Alerts page also apply immediately — the engine reloads them on every change. So
does ticking a new template under `alerts.enabled_templates`: the save instantiates it
into a live rule (see the note below for what that does *not* do).

So does `enrichment.*`. Enabling it, disabling it, and pasting a new
`aerodatabox_api_key` all take effect on save: the backend rebuilds the route provider
from what you just wrote and hands it to the running enrichment worker, which starts,
stops, or swaps to the new key accordingly. Routes begin appearing on the next eligible
callsign the receiver sees, with no restart
([issue #161](https://github.com/stevenpickles/flightsite/issues/161)). Turning it off
is equally immediate, and equally complete: the worker stops and the API client is
closed, so what [SECURITY.md §10](SECURITY.md) promises — that FlightSite contacts
AeroDataBox *only* while enrichment is enabled and a key is set — is unchanged and now
true from the moment you save rather than from the next restart. Lookups already
answered stay in the route cache, and sightings that were enriched keep their routes.

### Needs a restart

| Setting | Why |
|---|---|
| `receiver.*` | The decoder endpoint is read once when ingestion starts (see the first-run exception below) |
| `location.*` | The receiver reference point is fixed when the live store is built (see the first-run exception below) |
| `sighting.*` | Lifecycle thresholds are captured by the live store and persistence worker |
| `retention.high_res_metric_days` | Read when the metrics service is constructed |
| `timezone` | Analytics and receiver-metric day bucketing bind the zone at construction |
| `log_level`, `log_file_enabled` | Logging is configured before the app is built |
| `metadata.opensky_enabled` | The metadata source registry is built once at startup |

Every row above that the Settings UI can edit is badged **"Applies on next restart"**
there, so you never have to consult this table to find out. The badge sits on the
section header where the whole section waits — Decoder (`receiver.*`), Receiver
(`location.*`), Retention (`retention.high_res_metric_days`) — and on the individual
field where only part of a section does: the timezone under **Units & time**, and the
OpenSky toggle under **Aircraft Metadata**. `sighting.*`, `log_level` and
`log_file_enabled` have no Settings UI at all and are edited in `config.yaml`.

**The first-run exception.** `receiver.*` and `location.*` are restart-required only
once there is something running to disturb. On a fresh install nothing is polling yet,
so the setup wizard's save starts ingestion in place, points the receiver-metric
statistics poller at the decoder it just wrote, and anchors the live store at the
location it just wrote — finishing the wizard needs no restart. It is *changing* an
endpoint or a location afterwards that waits: the running adapter owns its connection
and its health history, and every already-observed aircraft carries a distance measured
from the old reference point until it is seen again.

### Two behaviors that will surprise you

**Alert templates.** `alerts.enabled_templates` is applied as a *delta*: a save
instantiates each template that save *added* to the list, and only those — which is
what stops a shipped rule you deleted from reappearing after some later, unrelated
save ([issue #110](https://github.com/stevenpickles/flightsite/issues/110)).

To get a deleted rule back, use the **Templates tab on the Alerts page**, which
instantiates one into a live rule immediately — or untick the template, save, tick it
again, and save.

**`alert_radius_nm`.** It reaches the alert engine only when rules are reloaded, which
happens at startup and on any alert-rule or watchlist change. Changing the radius
alone appears to do nothing until one of those events occurs. Restart, or make any
alert-rule edit, to apply it.

---

## Configuration reference

### Top level

| Key | Type | Default | Notes |
|---|---|---|---|
| `log_level` | `CRITICAL`\|`ERROR`\|`WARNING`\|`INFO`\|`DEBUG` | `INFO` | |
| `log_file_enabled` | bool | `true` | Rotating JSON logs in `<data-dir>/logs/`. Container stdout gets them either way |
| `units` | `aviation`\|`metric` | `aviation` | **Display only.** Storage and the API stay canonical: nm / ft / kt, UTC |
| `timezone` | IANA zone | `UTC` | e.g. `Europe/London`. Renders receiver-local times and buckets analytics days |
| `display_radius_nm` | float, 0 < x ≤ 10000 | `250.0` | Live-map radius. Aircraft beyond it are still stored and still count toward range records |
| `alert_radius_nm` | float or `null` | `null` | `null` means unlimited |

### `receiver` — the decoder endpoint

| Key | Type | Default | Notes |
|---|---|---|---|
| `host` | string | `127.0.0.1` | **Use a LAN IP, not a `.local` name** — see [INSTALL.md §9.5](INSTALL.md#95-decoder-connection-test-fails-on-a-local-hostname). `127.0.0.1` means *inside the container* |
| `port` | int, 1–65535 | `8080` | The decoder's HTTP port |
| `path` | string | `/data/aircraft.json` | Must start with `/` |
| `poll_interval_s` | float, 0 < x ≤ 60 | `1.0` | Decoders publish at roughly 1 Hz |

The endpoint is always plain `http://`; there is no HTTPS option, and no username or
password. Common paths:

| Decoder | Path |
|---|---|
| readsb / tar1090 | `/data/aircraft.json` |
| dump1090-fa | `/dump1090-fa/data/aircraft.json` |
| some tar1090 installs | `/tar1090/data/aircraft.json` |

FlightSite polls the JSON document over HTTP. Beast and SBS/BaseStation raw feeds are
**not** supported in this release. The decoder variant (readsb vs dump1090-fa) is
detected automatically, not configured — and "unknown" is a normal, healthy answer,
since modern builds of both serve a compatible document.

Use the wizard's or Settings' **connection test** rather than guessing. It reports
what went wrong in useful terms: `unreachable` (nothing answered — wrong host or
port, host down, firewalled), `http_error` (something answered with an error status —
usually a wrong path), or `invalid_document` (answered, but not an aircraft document).
On success it reports the aircraft count, how many have positions, and the detected
decoder flavor.

### `location` — the receiver reference point

| Key | Type | Default | Notes |
|---|---|---|---|
| `latitude` | float, −90…90 | `null` | |
| `longitude` | float, −180…180 | `null` | |
| `site_name` | string, ≤120 chars | `null` | |
| `antenna_height_ft` | float, −1400…30000 | `null` | |

`latitude` and `longitude` must be **both set or both null**. This is the reference
point for every distance, bearing, range ring, closest approach, farthest detection,
coverage figure and alert radius — get it roughly right or those numbers are
meaningless.

### `sighting` — lifecycle timing (seconds)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `stale_s` | float, ≤3600 | `15.0` | Shown as stale after this long with no update |
| `remove_s` | float, ≤7200 | `60.0` | Dropped from the live map |
| `close_s` | float, ≤86400 | `600.0` | Current sighting closed and persisted |

Must strictly increase: `stale_s < remove_s < close_s`.

### `retention`

| Key | Type | Default | Notes |
|---|---|---|---|
| `high_res_metric_days` | int, **7–30** | `14` | High-resolution receiver telemetry kept before downsampling to hourly/daily |

Only receiver telemetry is ever pruned. Sightings, tracks and lifetime statistics are
kept indefinitely, so the database grows for as long as you run it — measured at
~1.7 GB/year for a typical suburban receiver and ~20 GB/year at the SPEC §5 design
envelope. Neither figure is tunable from here: this setting only moves the
high-resolution telemetry window, which is a fixed-size fraction of the total. Plan
storage from [DATA_MODEL.md §9](DATA_MODEL.md) instead.

### `map`

| Key | Type | Default | Notes |
|---|---|---|---|
| `basemap` | string | `dark-aviation` | Style id from the basemap registry |
| `range_rings_enabled` | bool | `true` | |
| `range_ring_radii_nm` | list of float | `[50, 100, 150, 200]` | Up to 10, all > 0, unique; sorted on save |

### `enrichment` — optional online route lookup

| Key | Type | Default | Notes |
|---|---|---|---|
| `aerodatabox_enabled` | bool | `false` | |
| `aerodatabox_api_key` | secret | — | **Belongs in `secrets.yaml`, not here.** Required when enabled |

FlightSite is fully functional with enrichment off. This is the only setting that
sends anything about observed aircraft to a third party — see
[SECURITY.md §10](SECURITY.md).

Both settings apply on save, in either direction and including a change of key;
nothing here needs a restart. See [Applies immediately](#applies-immediately) above.

### `metadata` — aircraft metadata sources

| Key | Type | Default | Notes |
|---|---|---|---|
| `opensky_enabled` | bool | `false` | Opt in to the OpenSky aircraft database as a supplementary source |

The two default sources (Mictronics and the FAA registry) are always active and need
no configuration. OpenSky is separate because its licensing is genuinely unclear:
OpenSky's general Terms of Use restrict their data to non-profit research and
education and require a written licence for commercial use, while the aircraft
database's own page states it "is unlicensed and does not fall under our terms of
use" and is offered as-is. FlightSite does not decide that for you — the source stays
off until you turn it on, and while it is off no OpenSky provider is even
constructed, so a stock install never contacts OpenSky at all. See
[ADR-0013](adr/0013-opensky-metadata-source.md) and the
[licensing register](LICENSES.md).

When enabled, OpenSky **fills gaps only**: it may supply an operator, owner,
manufacturer/model or build year for an airframe where Mictronics and the FAA
registry supplied none, and it can never overwrite a value either of them provided.
Note also that the published dataset has not been refreshed since November 2024, so
treat it as a static backfill rather than a live feed.

### `notifications` — browser notifications

| Key | Type | Default |
|---|---|---|
| `enabled` | bool | `true` |
| `info` | bool | `false` |
| `interesting` | bool | `true` |
| `high` | bool | `true` |
| `critical` | bool | `true` |

Browser notifications are the only channel in v1, and they are delivered only while a
FlightSite tab is open on the Live Map. Permission is requested once, from the wizard
or Settings — never on page load.

### `alerts`

| Key | Type | Default | Notes |
|---|---|---|---|
| `enabled_templates` | list of string | `[]` | Shipped templates to instantiate; a save instantiates the ones it adds |

Valid ids: `military`, `government`, `police`, `first_ever`, `locally_rare`,
`locally_rare_type`, `watchlist`. Emergency squawks (7500/7600/7700) are always
reported and need no template.

Ids are not checked against the catalogue when saved — an unrecognised id is
persisted, then skipped with an `alert_template_unknown` warning in the logs, creating
no rule. If a template you enabled produced no rule, check the backend log for that
warning, and prefer the Alerts page's Templates tab.

---

## Secrets

Secrets live in `<data-dir>/secrets.yaml`, never in `config.yaml`. The file mirrors
the configuration tree and holds only secret leaves. In this release there is exactly
one:

```yaml
enrichment:
  aerodatabox_api_key: your-key-here
```

Handling:

- Written with `0600` permissions.
- The API returns `•••` for a configured secret, plus a separate "is it set" flag —
  the value itself is never served. Submitting the mask back means "leave unchanged";
  submitting `null` clears it.
- Masked in logs and redacted from diagnostics error records.
- **Excluded from backups by default** — `flightsite-backup` includes them only with
  an explicit `--include-secrets`, and records the choice in the archive manifest.

The key may also be supplied as `FLIGHTSITE_ENRICHMENT__AERODATABOX_API_KEY`, which is
often the better fit for a deployment that manages secrets outside the data directory.
Remember that an environment-pinned value cannot then be changed from the UI.

---

## Environment variables

Any configuration key can be set as an environment variable: prefix `FLIGHTSITE_`,
uppercase, and join nested keys with a **double underscore**.

```bash
FLIGHTSITE_LOG_LEVEL=DEBUG
FLIGHTSITE_RECEIVER__HOST=192.168.1.50
FLIGHTSITE_RECEIVER__PORT=8081
FLIGHTSITE_ENRICHMENT__AERODATABOX_API_KEY=…
```

These outrank both configuration files. Note that `compose.yaml` forwards only
`FLIGHTSITE_DEMO` into the container by default — Compose does not pass arbitrary host
variables through, so any other override needs its own `environment:` entry.

Variables that are **not** configuration keys:

| Variable | Default | Meaning |
|---|---|---|
| `FLIGHTSITE_DATA_DIR` | `/opt/flightsite/data` | Root of all persistent state. Resolved before configuration loads, so it cannot itself live in `config.yaml`. Fixed by the image; change the host side of the bind mount instead |
| `FLIGHTSITE_DEMO` | unset | Demo mode. Truthy values: `1`, `true`, `yes`, `on` (case-insensitive). Anything else, including `0` and empty, is off |
| `FLIGHTSITE_HOST` | `0.0.0.0` | Backend bind address |
| `FLIGHTSITE_PORT` | `8000` | Backend bind port, inside the container |
| `FLIGHTSITE_LOG_DIR` | `logs` | Only used when running the backend outside the container; the app passes `<data-dir>/logs` explicitly |

### Demo mode

`FLIGHTSITE_DEMO=1` replaces the decoder with a deterministic simulation — a fixed
seed, roughly 110 aircraft, 1 Hz updates, covering commercial, military, government,
police, MLAT, non-positioned, rare, first-ever, ground and emergency-squawk traffic.

The scenario is anchored to the clock at startup, so demo observations carry real
times and "today" on the Live Map and Analytics shows the traffic you are watching.
What is deterministic is the *content* — the same seed always produces the same
aircraft doing the same things on the same tick — not the timestamps, which advance
with the wall clock as a real receiver's would.

It is deliberately an environment switch rather than a configuration key, because it
has to work before any `config.yaml` exists. Unlike a real decoder, demo ingestion
starts at boot **regardless** of first-run state, so it needs no restart. The UI still
shows the setup wizard on a fresh data directory, since that is driven by the absence
of a configuration file; complete it once (no restart needed) or pre-seed a
`config.yaml`.

Demo mode is visible, not hidden: `/api/v1/health` reports `"demo": true`, the Health
page shows "Demo mode: On", and the Receiver page carries a Demo mode badge.

---

## Deployment variables (Compose only)

These are read by `compose.yaml` on the host and never reach the application.

| Variable | Default | Meaning |
|---|---|---|
| `FLIGHTSITE_HOST_DATA_DIR` | `/opt/flightsite/data` | Host side of the data bind mount. The container side never changes |
| `FLIGHTSITE_HOST_PORT` | `8090` | Host port the frontend is published on. The container always listens on 8080 |

Both can go in an `.env` file beside `compose.yaml`:

```
FLIGHTSITE_HOST_PORT=9000
FLIGHTSITE_HOST_DATA_DIR=/srv/flightsite/data
```
