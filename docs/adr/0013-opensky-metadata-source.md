# ADR-0013: OpenSky aircraft database as an opt-in, default-off metadata source

**Status:** Accepted (2026-09-01)

## Context

Roadmap slice 059 asks whether the OpenSky Network's aircraft database
(`aircraftDatabase.csv`) can join `mictronics` (slice 022) and `faa` (slice 023) as a
third aircraft-metadata source. It is attractive for exactly one reason: it carries
free-text `operator` and `owner` strings, a `manufacturername`, and a `built` date for
a large number of non-US airframes — precisely the fields Mictronics leaves blank and
the FAA registry only covers for US registrations. It would fill gaps, not replace
anything.

The blocker is licensing, and it is genuinely ambiguous rather than simply
permissive or simply hostile. Two OpenSky-published statements point in opposite
directions, both verified against the live site while writing this ADR:

- The **General Terms of Use & Data License Agreement**
  (`https://opensky-network.org/about/terms-of-use`) grants a "non-transferable,
  non-assignable, and terminable license to copy, modify, and use the data … solely
  for the purpose of non-profit research and non-profit education. No license is
  granted for any other purpose and there are no implied licenses in this AGREEMENT."
  It adds that "[a]ny use by a for-profit or commercial entity — including government
  and military contractors — requires a written license from OpenSky Network,
  regardless of purpose."
- The **Aircraft Database page** (`https://opensky-network.org/data/aircraft`), under
  its own "Citation and Use" heading, states the opposite for this dataset
  specifically: **"The aircraft database is unlicensed and does not fall under our
  terms of use. We do not provide support or guarantees of any kind — it is offered
  'as is'."** For publications it asks (does not require) a citation of Schäfer et
  al., *Bringing up OpenSky: A large-scale ADS-B sensor network for research*.

So the dataset's own page carves it out of the restrictive agreement, but "unlicensed"
is not itself a grant of rights — it is the absence of a stated license, which is a
weaker and murkier footing than a named permissive license would be. Note also that
"non-commercial" here is a *use* restriction on the licensee, not a share-alike or
attribution obligation on FlightSite; the risk it creates is to a downstream user who
runs FlightSite commercially, not to FlightSite's own MIT licensing.

Two things about the dataset's composition matter to the verdict. Its own page lists
its upstream sources as "Official aircraft registries, Various Basestation.sqb files,
Crowdsourced and manually collected data from various supporters, openflights.org,
ICAO Doc 8643" — a blend with no per-row provenance, and one that overlaps Mictronics'
own blend (both incorporate ICAO Doc 8643). And the same page carries an "Important
note" that the published dataset "is not up to date" and that "[t]he crowdsourced
aircraft database may be made available again at a further date": the artifact is a
frozen snapshot, `Last-Modified: Mon, 04 Nov 2024`, not a maintained feed.

`docs/LICENSES.md` already holds the two governing precedents, and this case sits
between them:

| Precedent | License situation | Verdict | Posture |
|---|---|---|---|
| **openAIP** (slice 028, [ADR-0012](0012-airspace-data-source.md)) | Explicit, unambiguous **CC BY-NC 4.0** | **Rejected outright.** A named non-commercial license is incompatible with an MIT project publishing public container images with no way to police downstream use. | Not shipped, not fetched, not bundled — no code path exists at all. |
| **Mictronics / tar1090** (slice 022) | **Ambiguous.** No data-specific license; the origin repo is GPLv3+ but that covers the *software*; the data blends FAA JO7340.2 and ICAO Doc 8643 with no per-row provenance. | **Accepted conservatively.** Treated as GPL-governed absent clarity. | **Fetch-on-demand only** — downloaded into the user's own deployment when they run "Update Aircraft Metadata", never bundled, shipped, or redistributed. |

OpenSky is the Mictronics *kind* of problem, not the openAIP kind. openAIP was
rejected because a clear license clearly forbade the use; here no license clearly
forbids anything — the dataset's own page disclaims the restrictive terms — but
neither does anything clearly permit it. Rejecting it outright would over-apply
ADR-0012's reasoning to a materially different situation; shipping it as a default
would under-apply the caution that situation deserves.

Per `docs/LICENSES.md`'s own note ("Genuinely ambiguous licensing questions are
escalated to the project owner rather than decided autonomously", SPEC §123), this was
escalated. The decision below is owner-approved.

## Decision

**FlightSite supports the OpenSky aircraft database as an opt-in, default-off,
fetch-on-demand metadata source.** Concretely, four commitments:

1. **Never bundled or redistributed.** Exactly the Mictronics posture.
   `flightsite/metadata/sources/opensky.py` downloads the CSV into the running
   deployment's own working directory, and only while an import is actually running.
   No OpenSky-derived bytes exist in FlightSite's source tree, releases, or container
   images.

2. **Default OFF**, which is the one place this goes *further* than Mictronics.
   `metadata.opensky_enabled` defaults to `false`, and the gate is at *construction*:
   when the setting is off the provider object is never built and the source is never
   registered, so it cannot appear in the update action, cannot be reached by an API
   caller, and cannot make a request. "Off" means absent, not merely skipped. A stock
   install therefore never contacts OpenSky at all, which is what makes the
   non-commercial question the user's own deliberate choice rather than a default
   FlightSite made on their behalf.

3. **The ambiguity is surfaced at the point of decision** — beside the toggle in the
   Settings metadata section, not buried in documentation the user will not read:
   *"OpenSky's aircraft database is provided as-is; their general terms restrict
   OpenSky data to non-commercial use — enable only if that fits your use."* Factual
   and concise; it states the constraint and declines to give legal advice or to
   pretend the question is settled. The register row in `docs/LICENSES.md` carries the
   full research trail behind it.

4. **Fill-gaps-only, ranked below both existing sources.** OpenSky contributes to
   exactly four fields — `operator_name`, `owner`, `model`, `manufacture_year` — and
   ranks strictly worse than `mictronics` and `faa` on every one of them. It is
   unranked on `registration` and `type_code`, which it must never influence: type
   code is the field FlightSite *groups* by, and a crowdsourced source disagreeing
   with Mictronics' ICAO Doc 8643 designators would silently fragment type
   statistics. Because `flightsite/metadata/precedence.py` already resolves per field
   with "silence never wins", this is expressed as a `FieldPriority` declaration
   rather than new merge code, and an OpenSky value can only ever land where both
   higher-precedence sources supplied `NULL`.

**The contact route to firmer ground is `contact@opensky-network.org`** — the address
OpenSky's own Terms of Use name for licensing questions. Asking them to state a
license for the aircraft database explicitly (or to confirm the "unlicensed" carve-out
in a form that can be pinned) is the action that would let a future slice revisit the
default-off decision. Until such an answer exists, default-off stands; this ADR is not
superseded by anyone's reading of the current wording, only by a clarification from
the source.

## Consequences

- **A new "ambiguous, opt-in" tier in the licensing register.** `docs/LICENSES.md`
  previously had two postures — compatible-and-fetched, or rejected. OpenSky's row
  establishes a third: fetched only on explicit opt-in, with the ambiguity disclosed
  in-product. Future slices facing an unclear license now have a precedent that is
  neither "ship it" nor "refuse it", and the openAIP row stays the precedent for a
  *clear* incompatibility, which it should.
- **The toggle takes effect at restart, not on save.** Because the gate is at provider
  construction inside `create_app`'s registry wiring, enabling the setting registers
  the source on the next backend start. This is deliberate — the alternative is a
  registry mutable at runtime, which would make "is this source registered?" a
  question with a time-dependent answer for every caller that reports per-source
  status. It matches how `enrichment.aerodatabox_enabled` already gates its provider.
- **A user who never opts in loses nothing they had.** OpenSky adds no field that
  Mictronics or the FAA registry already fills; by construction it only writes where
  both were silent. Turning it off again (and re-importing) returns exactly the
  previous resolved data, because provenance is recorded per field and no
  OpenSky-sourced value ever displaced another source's.
- **The dataset is stale and may not return.** The published snapshot has not been
  refreshed since November 2024 and OpenSky describes the crowdsourced database as
  something that "may be made available again at a further date". So this source's
  value will decay, and the download may eventually 404. That is survivable precisely
  because it is opt-in and gap-filling: a failed download leaves the previous import
  intact (`docs/SECURITY.md` §4), and a stale snapshot filling an otherwise-`NULL`
  owner is still better than nothing. It is, however, a reason not to promote this
  source's precedence later.
- **A 94 MB uncompressed download on a Pi.** Unlike Mictronics' ~8 MB gzipped
  artifact, OpenSky serves plain CSV with no compressed variant and no
  `Content-Encoding: gzip`. The adapter therefore follows `faa.py`'s download shape —
  stream to disk with a rolling hash — rather than `mictronics.py`'s, which buffers
  the whole artifact in memory and joins it (`_fetch`) and would peak near 190 MB on a
  Pi 4 at this size. Both shapes already exist in the codebase; this source takes the
  one meant for a large artifact, and the module docstring records why so the
  divergence from the sibling adapter is not mistaken for drift.
- **No schema migration.** OpenSky's four contributed fields already exist on
  `aircraft_metadata` / `aircraft_metadata_resolved`, and `metadata_sources` is keyed
  by an arbitrary source name, so registering a third aircraft-metadata source is
  purely additive wiring.
