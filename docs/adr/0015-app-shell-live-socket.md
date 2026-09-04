# ADR-0015: The app shell owns the live WebSocket

**Status:** Accepted (2026-09-04)

## Context

SPEC §48 says browser notifications "need to work while FlightSite is open in the
browser, including background/minimized tabs". Until this ADR, they did not — they
worked while FlightSite was open *on the Live Map*.

The live WebSocket (`/api/v1/ws/live`, `docs/API.md` §4) carries two unrelated
things on one connection: the live picture (`snapshot`/`delta`) and activity events
(`activity_batch`, §4.4). Alert notifications are dispatched from the activity
frames — slice 040 put `dispatchAlertNotification` on the socket's frame handler
rather than downstream of a store, because "already notified" has to survive a store
reset. The connection itself was opened by a `useEffect` in `useLiveConnection`,
which only `features/map/aircraft/AircraftLayer` mounted. So the socket opened when
the map mounted and closed when it unmounted, and every route change away from `/`
tore it down.

**That ownership was a deliberate decision, not an oversight**, and
`useActivityFeedStore`'s docstring recorded the reasoning: the standalone `/activity`
route reads the same events from `GET /api/v1/activity`, where they are already
durable, so opening a live socket for a page that renders history would spend a
connection to deliver rows the REST call already returned. `lib/api/receiver.ts`
documented the same division for `ReceiverInfo`. `docs/PRODUCT.md` §4.8 wrote the
consequence into the product description: *"'Open' means a tab on the Live Map,
which is where the connection that carries live alerts lives."*

That reasoning is sound for the *feed*, which has a durable REST source. It does not
hold for *notifications*, which have none: a notification is a live event or it is
nothing, and an alert that fires while the user's only tab sits on Analytics is
simply never delivered. The gloss in §4.8 was a documented narrowing of the SPEC,
not an implementation of it — which is what issue #105 reported.

The cost of hoisting is also smaller than it looked from inside the map. The socket
is one connection per tab either way, the server already bounds and evicts slow
consumers (§4.5), the store writes go through `getState()` and never render a
component that is not subscribed, and the map's own expensive machinery — the
interpolation frame loop, the GeoJSON rebuild, the label tiering — lives in
`useAircraftLayer`, which stays with the map and does not run on other routes.

## Decision

**`components/shell/AppShell` owns the live socket, for the life of the shell.**
`useLiveConnection` moves from `features/map/aircraft/` to `features/live/` and is
mounted by the shell; `AircraftLayer` no longer opens a connection.

Three parts to it:

1. **One socket per tab, on every app route.** `AppShell` is mounted once per
   session and is not re-created by navigation, so `map → analytics → map` opens no
   second connection and closes none. Activity frames — and therefore alert
   notifications — arrive wherever the tab happens to be parked.

2. **The shell, not `RootLayout`.** The setup wizard renders *outside* `AppShell`
   (`src/routes.tsx`), so a first-run session, which `RootLayout` redirects to
   `/setup`, holds no socket. That is where the line honestly belongs: there is
   nothing to stream to a receiver that has not been configured yet. It also
   preserves the previous behaviour, where the wizard was likewise chrome-free and
   map-free.

3. **Teardown splits along ownership, and stops being about routes.**

   | State | Owner | Cleared when |
   |---|---|---|
   | `aircraft`, `departing` | the socket | the connection is lost (`dropLivePicture`) |
   | `receiver` | the socket, but also `GET /api/v1/receiver` | never, except full teardown |
   | live activity tail | the socket | the connection is lost |
   | `selectedIcao`, `track`, `trackLive`, `trackBackfilledFrom` | the Live Map | `AircraftLayer` unmounts |
   | label-density latch | the Live Map | `AircraftLayer` unmounts |
   | notification dedupe set | the tab | never (bounded, `dedupe.ts`) |

   "Connection lost" is any `onStatus` other than `live`, which is exactly the
   transition `LiveSocket` already emits. Recovery needs no help: a reconnect opens
   with a `snapshot`, which the store applies wholesale, so the picture is rebuilt
   rather than merged into whatever was left behind.

   `receiver` is the one field held across an outage. It is configuration — units,
   timezone, site — that the REST API also serves, and `dispatch.ts` reads its
   `units` to compose a notification body on any route; dropping it during a
   reconnect would degrade formatting for no gain.

## Alternatives considered

- **Keep the map's ownership and document it.** This is what `docs/PRODUCT.md` §4.8
  already did, and it is the honest option only if SPEC §48 is read as "open on the
  Live Map". It is not what §48 says, and the reading makes the feature depend on
  which page a user happened to leave a tab on — the least discoverable possible
  failure mode for an alerting feature, since nothing anywhere reports that alerts
  are not being delivered.
- **A second, alerts-only socket** opened by the shell, leaving the map's socket
  alone. Rejected: two connections per tab where one suffices, doubling the server's
  fan-out and its slow-consumer bookkeeping, and needing a rule for which connection
  wins when both are open on the Live Map. The live picture and the activity events
  are already one protocol on one connection (§4); splitting the client against that
  grain buys nothing.
- **A subscription scope in the protocol** — a client frame saying "picture and
  activity" or "activity only", so a non-map route could take the cheap half.
  Rejected as out of scope: it is a wire-protocol change (`docs/API.md` §4 and the
  server's broadcaster), and the saving is a per-second delta frame on a LAN, which
  is not a cost worth a protocol revision. It stays available if a later slice ever
  measures the delta traffic as a real problem.
- **Hoisting to `RootLayout`, gated on `first_run`.** Rejected: it would make the
  socket wait for `GET /api/internal/config` on every load, delaying the first
  snapshot on the route that most needs it, to express a boundary that the route
  tree already draws for free (see decision 2).

## Consequences

- **One socket per tab on any FlightSite route**, where before there was one per
  mounted map. A user with the app open on Analytics or Settings now holds an open
  connection they previously would not have. On the trusted-LAN, single-user
  deployment this project targets (ADR-0010) that is a connection or two, well
  inside the fan-out the broadcaster is built and measured for.
- **Store traffic on non-map routes.** Delta frames now write `useLiveAircraftStore`
  about once a second regardless of route. Nothing on those routes subscribes to
  `aircraft`, so no component renders; the cost is the store's own per-frame rebuild
  of the record map, which is one pass over the live set. The map's frame loop,
  interpolation and GeoJSON serialization stay with `AircraftLayer` and do not run.
- **Memory stays bounded on a long-lived non-map tab**, and falls out of the
  ownership split rather than needing a special case. `aircraft` and `departing` are
  bounded by what the receiver can see (and `departing` is pruned on every frame);
  the live activity tail is capped at `MAX_LIVE_EVENTS`; the notification dedupe set
  is capped at `DEDUPE_CAPACITY`. The one structure that could have grown without
  limit is the selected aircraft's track — but the store accumulates track points
  *only* for a selected aircraft, and the selection is cleared when the map
  unmounts, so a tab left on `/analytics` for hours accumulates no track at all.
  (Even with a selection held, `TRACK_MAX_POINTS` caps it at 900.)
- **A reconnect no longer preserves the live picture, and a route change no longer
  destroys it.** Both are behaviour changes, in opposite directions, and both are
  improvements: a long outage used to leave a frozen map that only the status chip
  contradicted, while a trip to the Sightings page and back used to throw away a
  picture the connection was still perfectly able to supply. The user's selection
  now survives a reconnect, which it did before, and is cleared by leaving the map,
  which it also was before — the trigger changed, the observable behaviour did not.
- **`ReceiverInfo` reaches every route over the socket**, so the `useReceiverQuery`
  fallback is now a redundancy rather than the only source outside the map. It is
  kept: the store's copy arrives a connection and a frame late, and is absent before
  the first snapshot.
- **`features/live/` is a new feature folder** holding exactly one hook. The socket
  is no longer a map concern and keeping the file under `features/map/aircraft/`
  while the shell mounts it would have made the path lie. The two stores it feeds
  stay where they are — moving `useLiveAircraftStore` out of the map feature is a
  larger refactor with no behaviour attached to it, and is not part of this change.
