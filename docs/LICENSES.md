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
| Mictronics / tar1090 aircraft database | Offline aircraft metadata (type, registration, operator, military flag) | To be pinned exactly in slice 022 (upstream DB assembled from multiple community sources) | Expected yes — document in-app and in docs | Expected compatible; verify redistribution vs. fetch-on-demand terms | 022 | Pending verification |
| FAA Releasable Aircraft Registry | US registration, year, owner, make/model | US public domain (US government work) | No (courtesy citation recommended) | Compatible | 023 | Verified at planning level; pin at import |
| OurAirports | Airport dataset (idents, names, coordinates) | Public domain / CC0 | No (courtesy citation recommended) | Compatible | 027 | Verified at planning level; pin at import |
| openAIP airspace data | Airspace boundaries | **CC BY-NC 4.0** | Yes | **Likely INCOMPATIBLE** as a shipped default in an MIT project publishing public images; non-commercial restriction conflicts with downstream reuse | 028 | Blocked pending slice-028 evaluation — fallbacks: FAA NASR-derived US airspace (public domain), user-supplied airspace files |
| OpenFreeMap (tiles.openfreemap.org) | Default & light-aviation basemap vector tiles (OpenMapTiles schema, data from OpenStreetMap) | Tiles/style tooling: BSD-3-Clause (OpenMapTiles); underlying map data: **ODbL** (OpenStreetMap) | Yes — `© OpenMapTiles © OpenStreetMap contributors`, rendered via MapLibre's `AttributionControl`, always visible | Compatible — fetch-on-demand (tiles requested live from OpenFreeMap's public instance; FlightSite does not redistribute tile data). No API key. Public instance has no rate limit but is donation-funded (sustainability risk noted); self-hosting is available upstream if needed later. | 013 | Verified — see [ADR-0011](adr/0011-default-basemap-provider.md) |
| OpenStreetMap raster tiles (tile.openstreetmap.org) | `osm-raster` fallback basemap | Map data: **ODbL** (OpenStreetMap); tile images served by OSMF | Yes — `© OpenStreetMap contributors` | Compatible as a manually-selected, non-default fallback only. OSMF tile usage policy discourages this endpoint as a third-party app's *default*; FlightSite ships it opt-in, not as `DEFAULT_BASEMAP_ID`, keeping typical per-install traffic within "light use." No API key. | 013 | Verified — see [ADR-0011](adr/0011-default-basemap-provider.md) |
| Aircraft silhouette icon set | Type/category map icons | TBD — evaluated in slice 014 | Depends on set | Must be redistributable under MIT-compatible or attribution terms; candidates to be evaluated and pinned in slice 014 | 014 | Pending slice-014 selection |
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
