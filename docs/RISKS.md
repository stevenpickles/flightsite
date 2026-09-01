# FlightSite Risk Register

Material project and product risks (SPEC §91). Each risk has an id, likelihood,
impact, mitigation, status, and related roadmap slices. Statuses: `open`,
`mitigated`, `retired`.

## Summary

| ID | Risk | Likelihood | Impact | Status | Slices |
|---|---|---|---|---|---|
| R-01 | Mictronics/tar1090 metadata source changes or disappears | Medium | High | open | 021, 022, 025 |
| R-02 | AeroDataBox limits, outages, or pricing changes | Medium | Medium | open | 026 |
| R-03 | Raspberry Pi 4 performance envelope exceeded | Medium | High | open | 008, 009, 049, 050 |
| R-04 | SQLite long-term growth degrades queries/storage | Medium | High | open | 031, 033, 044, 050 |
| R-05 | Database corruption from power loss | Medium | High | open | 005, 043, 044, 052, 053 |
| R-06 | Browser notification platform limitations | High | Medium | open | 040 |
| R-07 | Map tile provider changes or licensing shifts | Medium | Medium | open | 013 |
| R-08 | readsb vs dump1090-fa format differences | Medium | Medium | open | 007 |
| R-09 | External dataset/asset licensing problems | Medium | High | open | 013, 014, 022, 027, 028 |
| R-10 | Single-maintainer / agent-drift process risk | Medium | Medium | open | all |
| R-11 | WebSocket fan-out with multiple browser clients | Low | Medium | open | 010, 049 |
| R-12 | Timezone/DST correctness errors | Medium | Medium | open | 031, 036 |

## Detail

### R-01 — Upstream metadata source changes (Mictronics/tar1090)
The primary offline metadata source is community-maintained; its format, hosting, or
license could change or the project could go dormant.
**Mitigation:** upstream format isolated inside the importer module (slice 021/022);
transactional import preserves the last working dataset indefinitely; normalized
internal schema means a replacement source is an importer, not a rewrite; attribution
and license terms documented at import-slice time.

### R-02 — AeroDataBox limits, outages, pricing
Route enrichment depends on a third-party paid API with rate limits.
**Mitigation:** enrichment is strictly optional and non-blocking; aggressive caching,
rate limiting, and a circuit breaker (slice 026); clean `Unknown` degradation is a
tested path; provider abstraction allows substitution behind the same interface.

### R-03 — Raspberry Pi 4 performance envelope
500 aircraft at 1 Hz plus analytics on a Pi 4 with SD-card I/O may exceed CPU, memory
(<1 GB budget), or I/O headroom.
**Mitigation:** performance treated as an architectural constraint from Phase 0
(write-behind persistence, ingestion never blocks on DB); perf harness with hard gates
(slice 049); Pi 4 baseline qualification before releases; storage qualification
(slice 050); informal perf sanity checks land early (slices 008/009), not at the end.

### R-04 — SQLite long-term growth
Years of sightings, track points, and metrics could degrade query latency and consume
Pi storage.
**Mitigation:** track simplification at sighting close; metric downsampling and
pruning (slice 033); daily rollups so analytics never scan raw history (slice 031);
automated maintenance (slice 044); multi-year synthetic qualification before v1.0.0
(slice 050).

### R-05 — Corruption / power loss
Homelab Pis lose power without warning.
**Mitigation:** WAL mode, startup integrity checks, no reliance on shutdown hooks
(slice 005); bounded-loss track checkpointing (slice 052) and open-sighting recovery (slice 053);
kill-during-write drills in CI; SQLite-safe, checksum-verified backups (slice 043);
corruption diagnostics rather than silent failure (slice 044).

### R-06 — Browser notification limitations
Notifications only work while a FlightSite tab is open; permission UX varies by
browser and OS; some platforms suppress background-tab notifications; browsers
withhold the API entirely from the plain-HTTP LAN origin FlightSite normally runs on.
**Mitigation:** scope is explicitly browser-only in v1 (SPEC §48); permission status
surfaced in diagnostics; degradation is clean and visible; richer channels are
tracked backlog items, not silent scope creep. Delivered in slice 040: each
non-delivering state — not asked, blocked, unsupported browser, insecure origin —
carries its own explanation and remedy in Settings, and alerts that could not be
shown are counted there, so a degraded install is visibly degraded.

### R-07 — Map tile provider changes
Free basemap providers change terms, styles, or availability.
**Mitigation:** basemap registry abstraction with multiple providers (slice 013);
provider choice recorded in an ADR with license terms; core functionality works with
tiles unreachable (tested); architecture permits future self-hosted tiles.

### R-08 — Decoder format differences
readsb and dump1090-fa JSON differ in fields and semantics; both must normalize
correctly.
**Mitigation:** adapter abstraction with real-world fixtures from both decoders
(slice 007); malformed-input fuzzing; capture/replay tool (slice 012) turns field
reports into regression fixtures.

### R-09 — External dataset and asset licensing
Aircraft metadata, FAA data, airport/airspace data, aircraft silhouette icons, and
basemap styles each carry license/attribution obligations; a mistake creates legal
exposure for an MIT-licensed project shipping public GHCR images. Two hazards are
already identified: (1) **openAIP airspace data is CC BY-NC 4.0** — its
non-commercial restriction is likely incompatible with shipping it as a default;
named fallbacks are FAA NASR-derived US airspace (public domain) or user-supplied
airspace files, and slice 028 must resolve this before airspace overlays ship.
(2) The **default basemap choice (slice 013)** carries usage-policy risk: a
self-hosted app shipping a shared default tile endpoint can breach free-provider
terms at aggregate scale; the slice-013 ADR must record policy compatibility and
whether a user-supplied key is required.
**Mitigation:** `docs/LICENSES.md` is the licensing register, created in Phase 0 and
updated in the same PR as any slice adding an external dataset/asset; license
verification is an acceptance criterion on every data/asset slice (013, 014, 022,
027, 028); the release checklist blocks shipping features whose register rows are
unresolved; genuinely ambiguous licensing questions escalate to the owner
(SPEC §123).

### R-10 — Single-maintainer / agent-drift process risk
Autonomous multi-agent development risks architectural drift, inconsistent
conventions, and quality erosion across many slices.
**Mitigation:** canonical roadmap with per-slice scope and acceptance criteria; Fable
self-review checklist on every PR (SPEC §104); `dev`-always-deployable invariant with
CI gates; ADRs for consequential decisions; docs-match-reality requirement in the
v1.0.0 definition of done.

### R-11 — WebSocket fan-out
Several simultaneous browser clients each receiving 1 Hz deltas for 500 aircraft
could stress the backend or stall the live path.
**Mitigation:** slow-consumer drop-and-resync design (slice 010); fan-out latency
measured in the perf harness (slice 049); realistic multi-client scenario in load
testing.

### R-12 — Timezone/DST correctness
UTC storage with receiver-local display, "today" bucketing, and busiest-hour
calculations are classic DST bug territory.
**Mitigation:** UTC-only storage and APIs (SPEC §15); single timezone-conversion
utility path on each side; explicit DST-transition fixtures in analytics bucketing
tests (slice 031) and day-boundary tests (slice 036).

## Maintenance Rules

- Fable updates this register during slice work: opening risks discovered during
  implementation, updating mitigations as slices land, and marking risks `mitigated`
  or `retired` with a one-line rationale (kept in the entry).
- Any slice whose PR materially changes a risk's posture must update the relevant
  entry in the same PR.
- New material risks get the next R-nn id; ids are never reused.
- The register is reviewed as part of every release qualification (`docs/RELEASE.md`).
