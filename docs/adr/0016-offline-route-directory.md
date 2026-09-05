# ADR-0016: An offline route directory as the primary origin/destination source

**Status:** Accepted (2026-09-05; owner decision recorded in the SPEC §28 amendment of
the same date, implemented in slice 071, issue [#173](https://github.com/stevenpickles/flightsite/issues/173).
Extends [ADR-0006](0006-provider-architecture.md), which stays the governing decision
for the *online* provider.)

## Context

SPEC §28 gave FlightSite one route source: **AeroDataBox**, an online provider behind
an API key. Slice 070 measured what that costs on the owner's receiver, and the numbers
are the whole reason this ADR exists:

- **2,200–2,650 distinct airline callsigns a day**, at roughly **190 lookups an hour**.
- **62 %** of a day's callsigns had already been heard the previous day — after only
  four days of history.
- **1 %** transient contacts (aircraft seen once, briefly).
- One legally restricted business jet retried **nine times in twelve minutes**, tripping
  the circuit breaker twice ([#165](https://github.com/stevenpickles/flightsite/issues/165)).

AeroDataBox credits on the feeder tier are earned slowly, and enrichment was spending
them faster than the feeder earned them. Slice 070 answered with instruments that ration
the spend: a per-callsign week-long TTL, learned schedules frozen for 30 days, a daily
lookup budget, priority ordering of the pending queue, and an airport-context
consistency check that invalidates a route the aircraft has just disproved. Together
those cut usage by roughly three quarters.

They do not change the shape of the problem. Every instrument in slice 070 is a way of
deciding **which** callsigns to pay for; none of them makes a callsign free. A receiver
in busy airspace still meets two thousand distinct flight numbers a day, and the great
majority of them are ordinary scheduled services flying the same pair of airports they
flew last season — data that is public, static, and already collected.

The owner's decision of 2026-09-05, recorded as an amendment to SPEC §28, was to admit
an offline route directory as the **primary** source, with AeroDataBox consulted only
for callsigns the directory does not know.

### What was available

Research on issue [#168](https://github.com/stevenpickles/flightsite/issues/168) and
during slice 071 evaluated four options.

| Candidate | Coverage | Licence | Verdict |
|---|---|---|---|
| **VRS standing data** (`github.com/vradarserver/standing-data`) | 619,828 callsigns, 1,576 CSV files | **CC0 1.0**, verbatim `LICENSE` in the repository | **Chosen** |
| **adsb.lol routeset** | Comparable | Open, but an **online API** — a network dependency per lookup | Rejected |
| **adsbdb.com** | Comparable | Free API, but its route data carries a **republication restriction** | Rejected |
| **Paid route APIs** (FlightAware, etc.) | Excellent | Commercial | Out of scope for a self-hosted homelab product |

Within the VRS option, three ways to obtain the data were measured from a developer
machine on 2026-09-05:

| Artifact | Measured | Notes |
|---|---|---|
| `…/archive/refs/heads/main.zip` | **7,063,160 B, 1.3 s** | `routes/schema-01/**` is 4,644,217 B of it compressed, 19,056,582 B uncompressed, across 1,576 files. CC0 `LICENSE` in the archive. |
| `virtualradarserver.co.uk/Files/StandingData.sqb.gz` | 15,558,890 B (`HTTP 200`, `Content-Type: application/x-gzip`) | Still published. **2.2× the size**, an undocumented compiled SQLite schema, and — decisively — **no data licence anywhere on the site**: `License.aspx` covers the *application source* under BSD-3-Clause, and the Data and Credits pages state no terms over the database. |
| Per-file fetches over the GitHub API | 1,576 requests | Rejected on arithmetic. |

The repository README names no other published artifact.

## Decision

**Import the VRS standing-data routes as a local table and consult it first. Keep
AeroDataBox for the callsigns it does not know.**

1. **A `routes` metadata source.** Registered in the slice-021 registry beside
   `mictronics`, `faa`, `opensky` and `airports`, fetched on demand through the existing
   "Update Aircraft Metadata" action, staged and promoted with the same transactional
   guarantee. It brings its own `ImportSink`, so it is excluded from the airframe
   precedence model exactly as `airports` is: it writes no `aircraft_metadata` row and
   has no claim about an airframe to rank. The artifact is the **repository archive**;
   only `routes/schema-01/**` is inflated, and the dataset version is the artifact's
   SHA-256.
2. **`route_directory`** (migration 0015): callsign primary key, the hyphen-separated
   ICAO path, the airline designator, the dataset version. Origin is the first code and
   destination the last; intermediate stops are kept. The import stages in a table
   rather than in memory, because the parsed corpus measures **138 MB** as Python
   objects — the aircraft-snapshot magnitude, not the airport one.
3. **The worker consults cache → directory → provider.** A directory hit is cached with
   `source: vrs` for the positive TTL and written to the sighting as
   `route_source: vrs`; the provider is never asked. A miss falls through to
   AeroDataBox under slice 070's budget, priority and breaker, unchanged.
4. **`provenance.route` carries `vrs` or `aerodatabox`.** Two reported sources, both
   still distinct from the locally inferred airport context beside them (SPEC §28).
5. **A contradicted directory row routes its re-ask to the provider.** Slice 070's
   consistency check applies to directory rows too, but with one addition: the callsign
   is skipped in the directory for the cache TTL, so a wrong row cannot be re-read,
   re-cached, re-contradicted and re-read forever.
6. **Last known route.** When a cached row has expired and neither the directory nor the
   provider can answer *now* — budget spent, breaker open, 429, timeout — the expired row
   is served, its expiry pushed 24 h out, logged once per callsign per UTC day, and
   counted in the diagnostics `enrichment.cache.stale_served` block.

## Alternatives considered

**adsb.lol's routeset API.** Open and free, and the coverage is comparable. It is an
*online* API, which means a route lookup remains a network round trip with a third-party
availability dependency — the thing this decision exists to remove. It would have
replaced a credit problem with a latency-and-uptime problem. Recorded as out of scope in
the slice's `out_of_scope`, not as unusable.

**adsbdb.com.** Free, well-documented, good coverage. Its terms carry a **republication
restriction** on the route data. FlightSite would not republish it — the data would live
on the user's own Pi — but the restriction is exactly the kind of ambiguity
`docs/LICENSES.md` says to escalate rather than decide, and a CC0 dataset of the same
coverage was available. Rejected on licence clarity, not on quality.

**A paid route API.** Solves coverage and freshness outright, and is the wrong shape for
a self-hosted product whose whole premise is that a Raspberry Pi in a spare room is
enough.

**AeroDataBox alone, with slice 070's instruments turned up further.** A longer TTL and
a smaller budget do reduce spend, and they reduce *coverage* in the same motion: the
routes not bought are simply not shown. The directory changes the trade rather than
tightening it.

**Bundling the dataset in the container image.** CC0 permits it. It is still not done,
for the reason every other row in `docs/LICENSES.md` gives: upstream changes
continuously, a bundled copy is stale the week it ships, and fetch-on-demand keeps the
posture uniform across every dataset FlightSite touches.

**Using the compiled `StandingData.sqb.gz`.** Twice the download, an undocumented
schema, and no licence statement. See the table above.

## Consequences

**Most routes become free.** A callsign the directory knows costs one indexed
primary-key read and no credit, ever. On the measured receiver the great majority of a
day's 2,200–2,650 callsigns are ordinary scheduled services, so the day's AeroDataBox
spend collapses onto the callsigns nobody has filed a public schedule for — which is
where the credits were worth spending in the first place.

**Community data goes stale, and that is the real cost.** The directory is built from
corrections VRS users submit. A retimed service, a seasonal re-route or a new flight
number is in it whenever somebody notices; nothing guarantees it is current. Three
things bound the damage:

- the airport-context consistency check catches a wrong route the moment the aircraft
  flies it, and sends the re-ask to the provider rather than back to the file;
- provenance is published, so a `vrs` route is visibly a route from a periodically
  imported dataset rather than a live lookup;
- re-importing is one click, and the dataset version is reported beside the source.

It is still true that a `vrs` route can be wrong in a way an AeroDataBox route would
not have been, and that FlightSite will show it until an aircraft disagrees or the
directory is re-imported. That is the trade this ADR accepts.

**A new outbound request.** One HTTPS GET to `github.com`, on demand, carrying nothing
of the user's — no callsign, no position, no key. `docs/SECURITY.md` §10 states it.

**Storage and one expensive migration.** The directory is ~620k narrow rows; the staging
table doubles that transiently during an import. Migration 0015 also **rebuilds
`sightings`** to widen `ck_sightings_route_source`, because SQLite cannot alter a `CHECK`
in place. On a three-year Scenario A database (1.64M sightings, five indexes) that is a
one-time cost measured in tens of seconds at the upgrade. It is paid once, and the
alternatives were to write a value the schema forbids or to edit the schema in place
through `PRAGMA writable_schema`, which is not a thing to do to a user's primary history
table unattended.

**No scheduled refresh in v1.** The directory updates only when the user runs "Update
Aircraft Metadata", which is SPEC §79's existing backlog item for scheduled metadata
updates and not this slice's business.

**The directory is consulted by the enrichment worker, which still requires a
configured provider to run.** An install with no AeroDataBox key gets no routes at all,
directory or otherwise, because the worker does not start without one — the structural
form of slice 026's "no key, no external call" guarantee. Letting the worker run
directory-only is a natural follow-up and is deliberately not in this slice: it changes
what "enrichment is off" means, which is a decision of the same kind as this one.
