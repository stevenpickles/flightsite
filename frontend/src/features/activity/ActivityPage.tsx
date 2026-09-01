/**
 * The standalone Activity view (roadmap slice 035, SPEC §55): the whole feed,
 * paginated server-side via `GET /api/v1/activity`, with the type filter and
 * page persisted in the URL.
 *
 * **Not a primary nav section.** SPEC §10 fixes the sidebar at seven, and the
 * roadmap gives the feed its home *in the Live Map experience* plus a fuller
 * view — so this route is reached from `ActivityPanel`'s "View all" link and
 * from a shared URL, exactly as `/sightings/:id` is reached from the sightings
 * log. That is also why this page builds its own heading rather than calling
 * `requireNavItem`, which throws for anything outside the seven.
 *
 * **REST only, deliberately.** The live socket belongs to the Live Map (see
 * `store/useActivityFeedStore.ts`), so this page shows what
 * `activity_events` holds and does not append live frames. Nothing is missing
 * as a result — every event the socket would have delivered is already a row
 * in that table by the time it is broadcast.
 *
 * Reuses the Aircraft page's pagination controls, which already handle the
 * `null` total (§2.4) this endpoint always returns by falling back to "a full
 * page came back" as the signal there is a next one.
 */

import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";
import { ActivityRow } from "@/features/activity/components/ActivityRow";
import { ActivityTypeFilter } from "@/features/activity/components/ActivityTypeFilter";
import { useActivityPageState } from "@/features/activity/hooks/useActivityPageState";
import { PAGE_SIZE } from "@/features/activity/lib/urlState";
import { useActivityQuery } from "@/lib/api/activity";
import { useReceiverQuery } from "@/lib/api/receiver";

export function ActivityPage() {
  const { state, setState } = useActivityPageState();
  const receiverQuery = useReceiverQuery();
  const listQuery = useActivityQuery({
    limit: PAGE_SIZE,
    offset: (state.page - 1) * PAGE_SIZE,
    // Omitted entirely when empty, so an unfiltered feed sends no `type` at
    // all rather than a parameter meaning "everything".
    types: state.types.length === 0 ? undefined : state.types,
  });

  const timezone = receiverQuery.data?.timezone ?? "UTC";

  return (
    <div className="flex h-full flex-col px-4 py-6 md:px-8">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight">Activity</h1>
        <p className="text-sm text-muted-foreground">
          Firsts, records and milestones — what happened while you weren&rsquo;t
          watching.
        </p>
      </header>

      <ActivityTypeFilter
        selected={state.types}
        onChange={(types) => setState({ types })}
      />

      {listQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading activity…</p>
      ) : listQuery.isError ? (
        <p className="text-sm text-destructive">
          Could not load the activity feed: {listQuery.error.message}
        </p>
      ) : listQuery.data.items.length === 0 && state.page === 1 ? (
        <p className="text-sm text-muted-foreground">
          {state.types.length === 0
            ? "Nothing has happened yet."
            : "No activity matches these filters."}
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <ul className="divide-y divide-border/60">
            {listQuery.data.items.map((event) => (
              <ActivityRow key={event.id} event={event} timezone={timezone} />
            ))}
          </ul>
          <AircraftPaginationControls
            page={state.page}
            pageSize={PAGE_SIZE}
            rowCount={listQuery.data.items.length}
            total={listQuery.data.total}
            onPageChange={(page) => setState({ page })}
          />
        </div>
      )}
    </div>
  );
}
