# ADR-0005: Track checkpointing, simplification, and packed storage at sighting close

**Status:** Accepted (2026-08-31; revised at the Phase 0 review gate — packed
row-per-sighting storage promoted from contingency to the v1 design). The
per-row storage figure below is **superseded in part by
[ADR-0014](0014-track-storage-cost.md)** (2026-09-04).

## Context

A sighting's full-resolution track (1 Hz × potentially an hour × 500 aircraft) is too
voluminous to keep forever on a Pi (SPEC §19), yet v1 must retain enough
ordered/timestamped path data that historical playback can be added later, and power
loss must not erase an active sighting's path (SPEC §71). Bézier fitting for
compression is explicitly ruled out. The Phase 0 storage model showed that at the
SPEC §5 load envelope (~500 simultaneous aircraft ⇒ ~15–20k sightings/day),
row-per-point storage of even *simplified* tracks exceeds 25 GB/year — unacceptable
for Pi-class storage — while a packed per-sighting encoding keeps the same data at
~8–9 GB/year.

## Decision

- **While a sighting is active:** the full-resolution track lives in memory in the
  live store and is **checkpointed to SQLite in batches** (persistence-worker cadence,
  ~30 s; `sighting_track_checkpoints`, row per point, integer enum codes) so an
  unclean shutdown loses at most the last uncheckpointed batch. Checkpoints are
  **lightly thinned** (collinear cruise points at unchanged altitude may be skipped);
  they are a crash-recovery record, not an archival one.
- **At sighting close:** the in-memory track is simplified with **Douglas-Peucker**
  (altitude-aware tolerance chosen and property-tested in slice 052), then written as
  **one `sighting_tracks` row per sighting**: a compact packed binary encoding
  (delta-encoded scaled integers, ~16 B/point) of the ordered, timestamped points —
  per point: time, position, altitude, ground speed, track, position source — plus
  `point_count` and `encoding_version`. Checkpoint rows are deleted in the same
  transaction.
- **After close:** only the packed simplified path exists, retained indefinitely
  (SPEC §65). Per-sighting reception statistics are computed before raw data is
  discarded.
- Points always remain real received/derived fixes — no curve fitting, no synthesized
  positions. The pack/unpack layer is a repository detail: callers see
  points-in/points-out, and the decoder ships with the encoder, keeping the data
  playback-capable per SPEC §19.

## Consequences

- Per-sighting track storage is **~1–2 KB of packed payload** in a single clustered
  row — roughly 20× smaller than row-per-point storage of the same simplified track —
  which is what makes multi-year retention feasible at the SPEC §5 envelope (see
  DATA_MODEL §9). **Amendment (slice 068, [ADR-0014](0014-track-storage-cost.md)):**
  that is the payload, not the cost on disk. Because this table is `WITHOUT ROWID`,
  its inline payload limit is 1002 bytes at SQLite's default 4096-byte page size, so
  54.5% of tracks spill a whole 4 KiB overflow page and slice 050 measured
  **2,868 B/row** — about 2.2× this figure, and 86% of a three-year database.
  ADR-0014 accepts that cost for v1 and defers the layout remedy; the packed encoding
  and the 20× improvement over row-per-point storage are unaffected.
- Simplification error is bounded and tested; extreme maneuvering keeps more points
  by construction of Douglas-Peucker. `encoding_version` makes format evolution an
  additive migration.
- Crash recovery has a defined contract: bounded loss (one checkpoint batch), and
  recovery closes orphaned sightings from their checkpointed points.
- **Amendment (slice 052):** the close path simplifies the union of the persisted
  checkpoint rows plus only the un-checkpointed in-memory tail, rather than a second
  full-resolution in-memory copy of the whole track. Keeping a full duplicate resident
  per open sighting would cost tens of MB at the SPEC §5 envelope and would have to
  outlive the live record. Consequence: every closed sighting's path passes through
  the lightly-thinned checkpoint representation (a normally-closed and a recovered
  sighting now differ only by the final un-checkpointed batch). This is acceptable
  because the checkpoint thinning tolerance is set an order of magnitude tighter than
  the close-time simplification epsilon, and a test asserts simplify(raw) ==
  simplify(thinned) on representative tracks. It also makes slice 053's recovery the
  same code path as a normal close.
- SQL cannot query individual track points (no per-point WHERE clauses). No v1
  feature needs that: every read is "the whole path for one sighting". A future
  feature needing point-level queries would require a superseding ADR.
- The delete-after-pack step makes sighting close a transactional sequence owned by
  the single writer (ADR-0001/0008).
