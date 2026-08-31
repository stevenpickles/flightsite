# ADR-0011: Default basemap provider (OpenFreeMap, no user-supplied key)

**Status:** Accepted (2026-08-31)

## Context

The Live Map (slice 013) needs a basemap layer under the receiver marker, range
rings, and — starting in slice 014 — live aircraft. FlightSite is a self-hosted,
offline-first project shipped as public MIT-licensed container images (§4, §25,
§28, §32 of `planning/SPEC.md`); the default map experience must work immediately
after `docker compose up`, with **no signup, no API key, and no paid account**, on
a homelab install that may have no internet access at all for its core function.

Candidates evaluated:

| Provider | Key required | Cost | Usage policy fit for a shipped default | Self-hostable |
|---|---|---|---|---|
| **OpenFreeMap** (tiles.openfreemap.org) | No | Free, donation-funded | Explicitly "no registration, no API keys, no rate limits" for the public instance (openfreemap.org) | Yes — Btrfs planet images published for self-hosting |
| CARTO basemaps | Yes for non-CARTO apps beyond free tier | Free tier + paid | Free tier is intended for CARTO's own platform; embedding it as a third-party app's silent default risks quota/ToS issues | No (hosted service) |
| OpenStreetMap raster (tile.openstreetmap.org) | No | Free | OSMF tile usage policy explicitly discourages this as the **default** for third-party applications ("heavy use," "no bulk downloading," asks larger deployments to run their own tile server); fine as an occasional/manual fallback, not as the thing every install hits by default | No (community-operated) |
| Self-hosted vector tiles (e.g. via `tileserver-gl` + a downloaded extract) | No | Free, but requires the user to download/manage a tile dataset | Best long-term fit for the offline-first goal, but real setup burden — a v1 requirement here would raise the bar for the wizard/first-run experience well beyond this slice's scope | Yes (this *is* the self-hosted option) |

## Decision

**OpenFreeMap is the default basemap provider**, via a custom "dark aviation"
vector style FlightSite builds itself on OpenFreeMap's OpenMapTiles-schema tiles
(`frontend/src/features/map/basemaps/darkAviationStyle.ts`, built from the shared
factory in `paletteStyleFactory.ts`). Building the style locally — rather than
pointing at OpenFreeMap's own hosted "liberty"/"dark" style JSON — keeps the exact
tiles, attribution, and color choices reviewable in this repository and lets the
palette match the app's dark theme tokens (`src/index.css`) precisely, at the cost
of maintaining a small custom style instead of consuming an upstream one directly.

Concretely, the basemap registry (`frontend/src/features/map/basemaps.ts`) ships
three keyless entries:

- `dark-aviation` (default) — the custom OpenFreeMap-based dark style.
- `light-aviation` — the same OpenFreeMap vector source and layer set, light
  palette, for daylight/high-glare use.
- `osm-raster` — plain OpenStreetMap standard raster tiles
  (`tile.openstreetmap.org`), as a universal, zero-dependency fallback a user can
  pick manually. It is deliberately **not** the default, per the OSMF tile usage
  policy note above; per-install traffic as an occasional manual option stays well
  inside "light use."

None of the three requires a user-supplied API key (`requiresKey: false` on every
registry entry) — this is a hard requirement for v1, not a preference, because
FlightSite ships no server-side secret-management step before the map is usable
and the setup wizard (slice 018) must not gate the Live Map on an external
account.

## Consequences

- **Attribution**: every style source carries a TileJSON-style `attribution`
  field (`© OpenMapTiles © OpenStreetMap contributors` for the OpenFreeMap-based
  styles, `© OpenStreetMap contributors` for the raster fallback), and
  `MapLibreMap` always mounts a MapLibre `AttributionControl` reading from those
  sources — attribution is never optional or hideable by basemap choice.
- **Licensing**: OpenMapTiles' schema/tooling is BSD-3-Clause/permissive, the
  underlying map data is OpenStreetMap (ODbL — attribution required, share-alike
  applies to redistributed *derived data*, not to rendered map display), and
  MapLibre GL JS itself is BSD-3-Clause. FlightSite does not redistribute tile
  data — it fetches tiles at runtime from the provider, which is the
  "fetch-on-demand" mode noted in `docs/LICENSES.md`. See that file's updated
  basemap row for the full compatibility record.
- **Sustainability risk**: OpenFreeMap's public instance is donation-funded and
  explicitly says as much. If it becomes unavailable or throttled in the future,
  the registry abstraction (this slice's core deliverable) means switching the
  default is a one-line change to `DEFAULT_BASEMAP_ID`, or adding a new registry
  entry — no map-rendering code depends on the specific provider. The `osm-raster`
  fallback and the self-hosting note below exist precisely for this risk.
- **Offline/tile-outage behavior**: whichever basemap is active, receiver marker
  and range rings are locally-generated GeoJSON — never fetched — so losing tile
  connectivity degrades the map to a dark canvas with rings/marker intact rather
  than losing core function (`MapLibreMap`'s `error`-event handling; verified by
  the tile-failure test).
- **Future self-hosted option**: OpenFreeMap publishes downloadable planet tile
  images specifically for self-hosting. A future slice could add a `self-hosted`
  registry entry (or a Settings-configurable custom tile URL) pointing at a
  user-run tile server for fully offline map tiles — the registry's `style: URL |
  StyleSpecification` union already accommodates this without a breaking change.
  This is deliberately not built now (out of scope for slice 013: "offline tile
  packs").
- No user-supplied key means no secret-handling code path for basemaps — nothing
  to mask, mask-check, or exclude from logs for this feature.
