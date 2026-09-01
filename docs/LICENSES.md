# Third-Party Data & Asset Licensing Register

FlightSite is MIT-licensed and ships public container images. Every external dataset,
API, library asset, or artwork it bundles or fetches by default must be compatible
with that, and its attribution obligations must be honored. This register is the
single source of truth for those obligations (referenced by risk R-09 in
`docs/RISKS.md`).

**Maintenance rule:** any slice that adds or changes an external dataset, asset, or
default provider MUST add or update its row here **in the same PR**. "Pinned" means
the exact upstream license text/version has been verified and recorded.

## Register

| Source | Provides | License | Attribution required | Compatibility | Owning slice | Status |
|---|---|---|---|---|---|---|
| Mictronics / tar1090 aircraft database (`wiedehopf/tar1090-db`, `csv` branch `aircraft.csv.gz`) | Offline aircraft metadata (type, registration, operator, military/interesting/PIA/LADD flags) | No license file covers the data specifically. `Mictronics/readsb` — the repo whose `webapp/src/db` is this data's origin — is **GPL v3, or any later version** (its `LICENSE`), incorporating GPL v2+ and BSD-licensed `dump1090` code. `wiedehopf/tar1090-db` (the repackaging repo this slice downloads from) carries no `LICENSE` file of its own. Mictronics' own `webapp/src/db/README` credits further blended sources: **FAA JO7340.2** for operator/callsign decode and **ICAO Doc 8643** for aircraft type data, neither separately licensed for redistribution. | Yes — in-app and here: "Aircraft metadata from the Mictronics/readsb aircraft database (github.com/Mictronics/readsb, GPLv3+), distributed via wiedehopf/tar1090-db (github.com/wiedehopf/tar1090-db); includes data derived from FAA JO7340.2 and ICAO Doc 8643." | **Fetch-on-demand only, not bundled.** `flightsite/metadata/sources/mictronics.py` downloads `aircraft.csv.gz` into the running deployment's own working directory only when a user runs "Update Aircraft Metadata"; FlightSite never bundles, ships, or redistributes the file in source, releases, or container images — the same posture as the OpenFreeMap/OSM rows below. No data-specific license was found distinct from the GPL covering the `readsb` *software*; absent that clarity this is treated conservatively as GPL-governed, which is why it stays fetch-on-demand-only rather than shipped as a default asset. | 022 | Verified — fetch-on-demand only; see the module docstring in `flightsite/metadata/sources/mictronics.py` for the full research trail |
| FAA Releasable Aircraft Registry | US registration, year, owner, make/model | US public domain (US government work) | No (courtesy citation recommended) | Compatible | 023 | Verified at planning level; pin at import |
| OurAirports | Airport dataset (idents, names, coordinates) | Public domain / CC0 | No (courtesy citation recommended) | Compatible | 027 | Verified at planning level; pin at import |
| openAIP airspace data | Airspace boundaries | **CC BY-NC 4.0** | Yes | **Likely INCOMPATIBLE** as a shipped default in an MIT project publishing public images; non-commercial restriction conflicts with downstream reuse | 028 | Blocked pending slice-028 evaluation — fallbacks: FAA NASR-derived US airspace (public domain), user-supplied airspace files |
| OpenFreeMap (tiles.openfreemap.org) | Default & light-aviation basemap vector tiles (OpenMapTiles schema, data from OpenStreetMap) | Tiles/style tooling: BSD-3-Clause (OpenMapTiles); underlying map data: **ODbL** (OpenStreetMap) | Yes — `© OpenMapTiles © OpenStreetMap contributors`, rendered via MapLibre's `AttributionControl`, always visible | Compatible — fetch-on-demand (tiles requested live from OpenFreeMap's public instance; FlightSite does not redistribute tile data). No API key. Public instance has no rate limit but is donation-funded (sustainability risk noted); self-hosting is available upstream if needed later. | 013 | Verified — see [ADR-0011](adr/0011-default-basemap-provider.md) |
| OpenStreetMap raster tiles (tile.openstreetmap.org) | `osm-raster` fallback basemap | Map data: **ODbL** (OpenStreetMap); tile images served by OSMF | Yes — `© OpenStreetMap contributors` | Compatible as a manually-selected, non-default fallback only. OSMF tile usage policy discourages this endpoint as a third-party app's *default*; FlightSite ships it opt-in, not as `DEFAULT_BASEMAP_ID`, keeping typical per-install traffic within "light use." No API key. | 013 | Verified — see [ADR-0011](adr/0011-default-basemap-provider.md) |
| Aircraft silhouette icon set | Type/category map icons | Original FlightSite assets, MIT (slice 014) | No — first-party artwork, covered by the repository's own `LICENSE` | Compatible by construction: no third-party rights are involved, nothing is fetched or redistributed, and downstream reuse inherits MIT | 014 | Verified — drawn in-repo as SVG paths in `frontend/src/features/map/aircraft/icons/silhouettes.ts`; no external icon set was adopted |
| MapLibre GL JS | Map rendering library | BSD-3-Clause | License text retained | Compatible | 013 | Verified |
| Map fonts / glyphs | Basemap typography, served via OpenFreeMap's glyph endpoint (Noto Sans) | Noto Sans: **SIL Open Font License 1.1** | Per OFL (no attribution required in rendered output; license text retained in this register) | Compatible | 013 | Verified |

## Notes

- "Fetch-on-demand" (user's deployment downloads data from upstream at runtime) and
  "redistribution" (data bundled in FlightSite images/releases) can carry different
  obligations; each row's pinning must state which mode FlightSite uses.
- Genuinely ambiguous licensing questions are escalated to the project owner rather
  than decided autonomously (SPEC §123).
- The release qualification checklist includes a documentation review; a release must
  not ship with any register row in an unresolved "blocked" state for a feature that
  release enables.
