# ADR-0014: Accept the measured `sighting_tracks` storage cost for v1

**Status:** Accepted (2026-09-04; issue #114, measured in slice 050, decided in
slice 068. Supersedes in part the storage-cost figure in
[ADR-0005](0005-track-checkpointing-and-simplification.md).)

## Context

[ADR-0005](0005-track-checkpointing-and-simplification.md) chose packed
row-per-sighting track storage and sized it at **"~1–2 KB in a single clustered
row"**; `docs/DATA_MODEL.md` §2.4 said ~1–1.5 KB and §9's growth arithmetic
carried ~1.3 KB per track into a prediction of **1.0–1.2 GB/year** for the
typical suburban receiver (Scenario A) and **12–14 GB/year** for the SPEC §5
design envelope (Scenario B).

Slice 050's multi-year qualification measured it (`docs/PERFORMANCE.md` §7.6,
§7.7). Over three synthetic years of Scenario A — 1,642,500 sightings,
1,510,946 packed tracks — `sighting_tracks` averages **2,868 bytes/row**, is
**86 % of the 5.032 GB database**, and drives measured growth of **1.68 GB/year**
against the 1.0–1.2 predicted. Everything else in the database together is
0.70 GB after three years, so this one table's per-row cost *is* the growth
figure.

**Why the estimate was wrong.** The packed encoding is exactly as cheap as
ADR-0005 says: 5 + 21 × `point_count` bytes, a mean payload of 1,265 B for the
mean 60-point track. What neither document accounted for is how SQLite stores
that record.

- `sighting_tracks` is a **`WITHOUT ROWID`** table (DATA_MODEL §2.4), so its
  rows live in an index B-tree, whose maximum **inline** payload is
  `(page_size - 12) × 64 / 255 - 23`.
- The product runs at SQLite's default **4096-byte page size** — `db/engine.py`
  never overrides it — which puts that limit at **1002 bytes**, and the limit
  applies to the whole record (blob plus `encoding_version`, `point_count`,
  `started_ms`), not to the blob alone.
- A record therefore exceeds the limit from about **47 retained points**
  onward, and the remainder spills into a dedicated 4 KiB **overflow page**,
  nearly all of which is slack. A 60-point row measured in isolation costs
  **4,682 B** on disk for its 1,265 B of payload.
- The retained-point distribution has a real tail — median 50, p90 110, p99 211
  — so **54.5 % of tracks spill**. The measured average of 2,868 B/row is a
  blend of the sub-47-point half that still fits inline and the half that pays
  a whole extra page.

The estimate was not arithmetic that got done wrongly; it was arithmetic that
stopped one layer too early, at the encoded payload rather than at the page the
payload lands on. Scenario B inherits the cost unchanged — measured at
2,867 B/row against Scenario A's 2,868, i.e. per-sighting cost does not depend
on traffic density — so its projection is **20.06 GB/year against the 12–14
predicted**, about 60 GB over three years against 36–42.

Three remedies were measured or costed (below). Each changes an on-disk
parameter or a table format, so each needs a migration story for databases that
already exist on users' Pis. Meanwhile the qualification's three **hard** gates
all passed: retention pruning, downsample coverage and the multi-year dataset
itself. Nothing about the product is broken by the extra bytes — the documents
describing it are simply wrong, and SPEC §114 requires architecture
documentation to match reality.

## Decision

**Accept the measured cost for v1. Correct the documents. Defer the layout
remedy, with its numbers recorded here.**

1. **The measured figures become the documented ones.** `docs/DATA_MODEL.md`
   §9 now states **~2.9 KB per packed track row**, **~1.7 GB/year** for
   Scenario A (5.03 GB over three years) and **~20 GB/year** for Scenario B
   (~60 GB over three years). The 1.0–1.2 / 12–14 GB/year figures are retained
   only as the labelled *design estimate*, so that the size of the gap stays
   visible.

2. **Retention and sizing guidance derived from the old prediction is
   corrected with it.** Scenario B no longer fits the "64–128 GB SD card or USB
   SSD" §9 recommended: at ~60 GB before any backup, and with
   `maintenance.policy` refusing to `VACUUM` without free space of twice the
   database size, that receiver needs **128 GB or more, and realistically an
   SSD**. Scenario A's three-year database is 5.03 GB, not 3–4 GB.
   `docs/INSTALL.md`'s disk row now quotes real per-year growth instead of
   pointing at a document.

3. **No code, schema, pragma or migration changes in this decision.** In
   particular the `db_bytes_per_sighting ≤ 2000` reference budget
   (`docs/PERFORMANCE.md` §7.2.2) and the scenario predictions encoded in
   `perf/storage_qualification/scenarios.py` **stay at the design estimate**
   rather than being re-baselined onto the measured cost. Re-baselining them
   would make every future run report "within budget" and quietly retire the
   deferred remedy; leaving them means every qualification run keeps printing
   the overrun, which is exactly the standing reminder this deferral needs. A
   reference budget does not fail a build (§1's hybrid model), so this costs
   nothing but honesty.

4. **Backlog item (mirrored into the roadmap backlog by the orchestrator, not
   edited here):** *Storage — revisit the packed-track on-disk layout: give
   `sighting_tracks` a rowid and/or raise `page_size` to 16384, with a
   migration path for existing databases (pragma + `VACUUM`, or a data
   migration of ~86 % of the file) and a re-run of the `docs/PERFORMANCE.md` §7
   qualification. Deferred by ADR-0014; revisit triggers are listed in its
   Consequences.*

### Rationale

The product works, the multi-year qualification passed on the measured growth,
and the runtime target has moved: the current reference hardware baseline is a
**Raspberry Pi 5 with an NVMe SSD** (`docs/PERFORMANCE.md` §5.5), where 5 GB
after three years of typical traffic is unremarkable. Every remedy costs a
migration executed against user data on a Pi — the class of change most likely
to lose someone's history — and no v1 requirement justifies taking that risk to
recover space that the target hardware has. Documentation that overpromises by
40 % is a real defect; it is also the one defect here that can be fixed without
touching a byte of anyone's database.

## Alternatives considered

| Option | Measured effect | Migration story | Verdict |
|---|---|---|---|
| **`page_size = 8192`** | Inline limit ~95 points; tracks spilling fall 54.5 % → **14.8 %**; `sighting_tracks` 2,868 → **2,282 B/row**; Scenario A 1.68 → **1.38 GB/year** | Pragma is settable only on an empty database or through a full `VACUUM` — for existing installs, a documented rewrite of the whole file that holds the single writer lock throughout (44.7 s for 5 GB on a dev machine; longer on a Pi) and needs the file's size again in free space | **Deferred.** Recovers only about a third of the excess — still outside §9's prediction — for the full cost of the migration. The worst ratio of the three. |
| **`page_size = 16384`** | Inline limit ~193 points; spills fall to **1.4 %**; `sighting_tracks` → **1,582 B/row**; Scenario A → **1.03 GB/year**, three years 3.09 GB; Scenario B → ~12.3 GB/year | Same `VACUUM` rewrite as above | **Deferred.** The only measured option that reaches the original prediction, but it applies to *every* table, so a 16 KiB page changes read amplification for the small hot tables too — unmeasured on Pi storage. Trading a known cost for an unmeasured one, on user data, for space the Pi 5 NVMe baseline has. |
| **Give `sighting_tracks` a rowid** | Not measured. A rowid table's inline limit is `page_size - 35` = **~4,061 B** at today's page size, past the p99 (211 points ≈ 4,436 B — so even the tail mostly fits), and only this one table changes | A schema change plus a data migration of the table that *is* 86 % of the file, on a Pi, with the database offline | **Deferred.** Likely the cheapest steady-state answer and the most surgical in blast radius per table — but it is the most expensive to perform, it is unmeasured, and it gives up the clustering ADR-0005 chose deliberately. Wants measurement before it wants a migration. |
| **Tiered / lossy track retention** | Would cut the table directly | Would relax SPEC §65's retain-indefinitely rule | **Rejected.** DATA_MODEL §9 named this as the lever if Scenario B busted its budget. It is the wrong lever: the overrun is slack in a storage parameter, not too much data. Discarding user history to work around a page-size default is not a trade v1 should make. |
| **Change the simplification epsilon** to keep the mean track under ~46 points | Not measured | None — a constant | **Rejected.** It would buy space by degrading the archived path for every sighting, and it is fragile: the fix would be one epsilon tweak or one busy-airspace day away from spilling again. ADR-0005's accuracy contract is not the place to absorb a storage-layout problem. |

## Consequences

- **What the documents now promise.** DATA_MODEL §9 predicts ~1.7 GB/year
  (Scenario A) and ~20 GB/year (Scenario B) and sizes storage from those;
  ADR-0005's "~1–2 KB" is annotated as the payload cost with the on-disk cost
  beside it; DATA_MODEL §2.4, INSTALL.md's disk requirement and
  CONFIGURATION.md's retention note agree with them. A reader can no longer
  arrive at a card size from a figure the product will exceed.
- **The overrun stays visible.** `db_bytes_per_sighting` keeps failing as a
  reference budget on every scenario-scale run, and `PERFORMANCE.md` §7.7's
  finding stays in place with this ADR recorded as its disposition. The day
  someone applies a remedy, the budget is what tells them it worked.
- **The gap is bounded and known, not open-ended.** Growth is 1.4× the old
  prediction and per-sighting cost is independent of traffic density (measured
  across a twelvefold difference), so any receiver's multi-year size can be
  projected from a single number.
- **Revisit when any of these happens**, and treat each as a trigger for the
  backlog item rather than a new judgement call:
  1. A Raspberry Pi storage baseline (§7.8) measures `sighting_tracks` above
     **~3,200 B/row**, or Scenario A growth above **2.0 GB/year** — i.e. the
     cost is worse on real hardware than on the development machine.
  2. A user reports storage exhaustion attributable to track storage, or a
     `VACUUM` permanently refused for lack of free space (§7.7's guard) on a
     database whose size this ADR predicted.
  3. Any other change requires a migration of `sighting_tracks` — the rowid
     conversion should ride along with it rather than be performed for its own
     sake.
  4. The reference hardware baseline moves back to SD-card storage, or SPEC
     §5's envelope rises enough that Scenario B's ~60 GB stops fitting
     commodity storage.
- **A future remedy needs a superseding ADR and a re-run of §7**, not a quiet
  pragma change: DATA_MODEL §9 is explicit that a growth deviation is
  reconciled by ADR, and this one now is.

## Numbers

Measured in slice 050 on a development machine (Windows 11 AMD64, Python
3.12.10); full context in `docs/PERFORMANCE.md` §7.6–§7.7. Scenario A is three
years (1,095 days, 1,642,500 sightings); Scenario B is 30 days (541,980
sightings) projected per year.

| Figure | Design estimate | Measured |
|---|---|---|
| `sighting_tracks` per row | ~1–2 KB (ADR-0005), ~1.3 KB (§9) | **2,868 B** (Scenario B: 2,867 B) |
| Packed payload per row | 5 + 21 × points | 1,265 B at the mean 60 points |
| Bytes per sighting, whole database | ~2,000 | **3,064** (Scenario B: 3,042) |
| Scenario A growth | 1.0–1.2 GB/year | **1.68 GB/year** (5.03 GB over 3 years) |
| Scenario B growth | 12–14 GB/year | **20.06 GB/year** (~60 GB over 3 years) |
| `sighting_tracks` share of database | — | **86 %** (4.334 GB of 5.032 GB) |

Why, and what each remedy would do to it:

| Page size | Inline limit | Tracks that spill | `sighting_tracks` | Scenario A growth |
|---|---|---|---|---|
| **4096 (today)** | 1002 B ≈ 46 points | **54.5 %** | **2,868 B/row** | **1.68 GB/year** |
| 8192 | ~95 points | 14.8 % | 2,282 B/row | 1.38 GB/year |
| 16384 | ~193 points | 1.4 % | 1,582 B/row | 1.03 GB/year |
| rowid table, page 4096 | `page_size - 35` ≈ 4,061 B ≈ 192 points | not measured | not measured | not measured |

Retained-point distribution behind those spill rates: mean 60, median 50,
p90 110, p99 211.
