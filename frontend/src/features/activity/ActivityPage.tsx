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

import { Fragment } from "react";

import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";
import { ActivityRow } from "@/features/activity/components/ActivityRow";
import { groupActivityByDay } from "@/features/activity/lib/dayGroups";
import { ActivityTypeFilter } from "@/features/activity/components/ActivityTypeFilter";
import { useActivityPageState } from "@/features/activity/hooks/useActivityPageState";
import { PAGE_SIZE } from "@/features/activity/lib/urlState";
import {
  QueryErrorBanner,
  QueryErrorState,
} from "@/features/history/components/QueryError";
import { EmptyResult } from "@/features/history/components/EmptyResult";
import { RefreshStatus } from "@/features/history/components/RefreshStatus";
import { TimezoneNote } from "@/features/history/components/TimezoneNote";
import { ACTIVITY_REFRESH_MS } from "@/features/history/lib/refresh";
import { useActivityQuery } from "@/lib/api/activity";
import { useReceiverQuery } from "@/lib/api/receiver";

export function ActivityPage() {
  const { state, setState } = useActivityPageState();
  const receiverQuery = useReceiverQuery();
  // The feed's whole promise is "what happened while you weren't watching",
  // so page 1 polls — the fastest of the three cadences, and still REST only:
  // the live socket stays the Live Map's (`features/history/lib/refresh.ts`).
  const refetchInterval = state.page === 1 ? ACTIVITY_REFRESH_MS : false;
  const listQuery = useActivityQuery(
    {
      limit: PAGE_SIZE,
      offset: (state.page - 1) * PAGE_SIZE,
      // Omitted entirely when empty, so an unfiltered feed sends no `type` at
      // all rather than a parameter meaning "everything".
      types: state.types.length === 0 ? undefined : state.types,
    },
    { refetchInterval },
  );

  const timezone = receiverQuery.data?.timezone ?? "UTC";

  return (
    <div className="flex h-full flex-col px-4 py-6 md:px-8">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight">Activity</h1>
        <p className="text-sm text-muted-foreground">
          Firsts, records and milestones — what happened while you weren&rsquo;t
          watching.
        </p>
        <TimezoneNote className="mt-1" timezone={timezone} />
        <RefreshStatus
          className="mt-1"
          updatedAt={listQuery.dataUpdatedAt}
          isFetching={listQuery.isFetching}
          onRefresh={() => void listQuery.refetch()}
          intervalMs={refetchInterval === false ? null : refetchInterval}
        />
      </header>

      <ActivityTypeFilter
        selected={state.types}
        onChange={(types) => setState({ types })}
      />

      {listQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading activity…</p>
      ) : listQuery.data === undefined ? (
        <QueryErrorState
          message={`Could not load the activity feed: ${listQuery.error?.message ?? "the request failed"}`}
          onRetry={() => void listQuery.refetch()}
          isRetrying={listQuery.isFetching}
        />
      ) : (
        <>
          {/* Before this, recovering meant clicking a filter chip — which
           * worked only because it made a new query key, and silently
           * changed what the user had asked for (review R2-04). */}
          {listQuery.isError && (
            <QueryErrorBanner
              message={`Could not refresh the activity feed: ${listQuery.error.message}.`}
              onRetry={() => void listQuery.refetch()}
              isRetrying={listQuery.isFetching}
            />
          )}
          {listQuery.data.items.length === 0 ? (
            <EmptyResult
              message={
                state.types.length === 0
                  ? "Nothing has happened yet."
                  : "No activity matches these filters."
              }
              page={state.page}
              onBackToFirstPage={() => setState({ page: 1 })}
            />
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <ul className="divide-y divide-border/60">
                {groupActivityByDay(listQuery.data.items, timezone).map(
                  (group, index) => (
                    // `index` in the key as well as the day: an unordered
                    // page would produce the same day twice, and a duplicate
                    // React key would be a second bug on top of the first.
                    <Fragment key={`${group.key}-${index}`}>
                      <li className="bg-secondary/40 px-4 py-1.5">
                        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          {group.label}
                          {group.label !== group.key && (
                            <span className="ml-2 font-normal normal-case tracking-normal">
                              {group.key}
                            </span>
                          )}
                        </h2>
                      </li>
                      {group.events.map((event) => (
                        <ActivityRow
                          key={event.id}
                          event={event}
                          timezone={timezone}
                        />
                      ))}
                    </Fragment>
                  ),
                )}
              </ul>
              <AircraftPaginationControls
                page={state.page}
                pageSize={PAGE_SIZE}
                rowCount={listQuery.data.items.length}
                total={listQuery.data.total}
                noun={{ singular: "event", plural: "events" }}
                onPageChange={(page) => setState({ page })}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
