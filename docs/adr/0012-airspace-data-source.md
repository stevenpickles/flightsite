# ADR-0012: Airspace overlay data source (user-supplied GeoJSON, no shipped default)

**Status:** Accepted (2026-09-01)

## Context

Roadmap slice 028 asks for an airspace boundary overlay "from a license-compatible
open source" alongside the airport overlay (slice 027's dataset), flagging that
openAIP — the obvious, most complete source of worldwide airspace polygons — is
**CC BY-NC 4.0** and therefore "likely incompatible" as a shipped default in an
MIT-licensed project that publishes public container images (`docs/LICENSES.md`'s
openAIP row, entered pending this ADR). FlightSite must never depend on a
non-commercial-only license for anything it ships by default (§4, §25, §28, §32 of
`planning/SPEC.md` — offline-first, self-hosted, MIT, no paid dependency for core
function); a license that forbids commercial use is incompatible with that on its
face; FlightSite itself is free, but "distributed under MIT, ships container images
the public can run" does not stop a downstream user from doing something openAIP's
license would call commercial, and there is no way to know or constrain that at the
point the data is baked into a shipped default.

Candidates evaluated:

| Source | Coverage | License | Fit for a shipped v1 default |
|---|---|---|---|
| **openAIP** | Worldwide, actively maintained, richest airspace class/altitude detail | **CC BY-NC 4.0** | **Rejected.** Non-commercial restriction is incompatible with an MIT project shipping public images with no way to police downstream use. Never shipped as a default, in this slice or later, absent a license change upstream. |
| **FAA NASR 28-day subscription** (shapefile / `.dat` distribution, `Class_Airspace` and related layers) | US only | US public domain (17 U.S.C. §105, same footing as the FAA Releasable Aircraft Registry already pinned in `docs/LICENSES.md`, slice 023) | **Not built this slice.** Licensing is clean and it is the natural US default, but NASR's shapefile/fixed-width `.dat` formats need their own parser, a 28-day-cycle refresh story, and a decision about which of its many layers ("Class Airspace" alone has multiple sub-layers, plus MOAs, restricted areas, etc.) belong in a v1 overlay — real scope, not a data-source substitution. Recorded below as a follow-up roadmap candidate rather than attempted inside this slice. |
| **User-supplied GeoJSON** (`<data_dir>/airspace.geojson`) | Whatever the user provides — worldwide if they source it, none if they don't | Whatever the user's own source's license is; FlightSite ships no data and asserts no rights over the file | **Built this slice.** Zero licensing risk to FlightSite (nothing is bundled, fetched by default, or redistributed), works in any country a user cares to source data for (a UK user can drop CAA-derived boundaries, a US user can drop their own NASR extract, converted to GeoJSON, etc.), and degrades to "no overlay" — not an error — on every install that does not supply one. |
| **Ship no default airspace at all** | N/A | N/A | **Built this slice**, paired with the user-supplied option above — the only way to have an airspace *feature* in v1 without either an incompatible license or unbuilt NASR tooling. |

## Decision

**FlightSite ships no default airspace data.** The airspace overlay is driven
entirely by a user-supplied GeoJSON `FeatureCollection` at
`<data_dir>/airspace.geojson` (`flightsite/airspace/loader.py`), served read-only at
`GET /api/v1/airspace`. An install that has never placed the file gets an empty
`FeatureCollection` back — the same documented "no data" shape §2.7 already uses
elsewhere in the API — never an error, a 404, or a UI warning banner. A user who
wants airspace boundaries sources their own extract (from openAIP under its own
terms for personal use, from a national AIP, hand-drawn, converted from NASR
themselves, anything that produces valid GeoJSON) and drops it in their own data
directory; FlightSite never fetches, bundles, or redistributes anything on their
behalf, so nothing about their choice of source becomes FlightSite's licensing
obligation.

This is deliberately **not** "ship openAIP" (rejected above — the license makes
that a non-starter regardless of attribution) and deliberately **not** "build FAA
NASR parsing now" (real, scoped work that roadmap slice 028 did not budget for —
see Consequences).

The loader validates on every read rather than trusting the file blindly: it must
parse as JSON, be a top-level `FeatureCollection`, stay under a 10 MB size cap, and
every feature's geometry must carry plausible WGS-84 coordinates (`flightsite/
airspace/loader.py::load_airspace`). Anything that fails any of those checks —
missing file, oversized file, invalid JSON, wrong shape, an unusable coordinate —
is logged once and answered with the same empty collection a stock install gets,
so a client can never distinguish "no file" from "a file that failed validation"
and the map degrades silently.

## Consequences

- **No airport-overlay-style "Pinned" licensing row for airspace.** `docs/
  LICENSES.md`'s airspace row records "user-supplied, no data shipped" rather than
  a dataset with a compatibility verdict — there is nothing FlightSite bundles or
  fetches to evaluate. The openAIP row is updated to "Resolved: not shipped" with
  a pointer to this ADR, rather than left "Blocked pending slice-028 evaluation".
- **US users get no default airspace**, unlike the airport overlay (OurAirports,
  worldwide, public domain, slice 027). This is a real capability gap relative to
  "the richest possible v1", accepted deliberately: shipping openAIP to close it
  would violate the license, and shipping FAA NASR to close it for the US alone is
  real, separately-scoped parsing work (see the follow-up below), not a
  same-slice substitution.
- **Follow-up roadmap candidate: FAA NASR-derived US default airspace.** A future
  slice could add an opt-in importer — analogous to `flightsite/airports/
  ourairports.py` and `flightsite/metadata/sources/faa.py` — that downloads the
  current 28-day NASR subscription, parses the `Class_Airspace` shapefile (and
  whichever companion layers are judged worth it: MOAs, restricted/prohibited
  areas), and writes normalized GeoJSON into the same `airspace.geojson` path this
  slice's loader already reads — meaning the loader, the API endpoint and the
  frontend layers built in this slice need **no changes** to consume it; only an
  importer needs to be built. That importer is explicitly out of scope here: it is
  its own data pipeline (shapefile/`.dat` parsing, a refresh cadence, a layer
  inclusion decision), not a data-source swap.
- **The overlay can be worldwide in practice, at zero cost to FlightSite**, because
  the format is just GeoJSON and the source is entirely the user's choice — this is
  a strictly larger addressable case than "US only via NASR" would have been, at
  the cost of shipping nothing to a user who does not go find their own data.
- **No secret-handling or fetch-on-demand code path for airspace** — unlike the
  aircraft metadata and OurAirports rows in `docs/LICENSES.md`, FlightSite never
  makes an outbound request for this feature at all, on behalf of anyone. The file
  either exists in the user's own data directory or it does not.
- **Validation-on-every-read has a bounded, known cost**: at the 10 MB cap, parsing
  and walking every feature's coordinates once per `GET /api/v1/airspace` is a
  request-path cost paid only by a user who both supplied a file and has the
  layer's toggle on — not a cost the live aircraft path (`docs/ARCHITECTURE.md`
  §3.1) or a stock install pays at all.
