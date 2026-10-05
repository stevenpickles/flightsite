/**
 * The Sightings page (roadmap slices 030 and 098, SPEC §57 as amended
 * 2026-10-05): what the receiver heard in a time window, three ways.
 *
 * - **Sightings** — the chronological log of every observation period,
 *   paginated server-side via `GET /api/v1/sightings`.
 * - **Aircraft** — one row per distinct airframe heard in the window
 *   (`GET /api/v1/analytics/aircraft`).
 * - **Types** — one row per distinct ICAO type heard in the window
 *   (`GET /api/v1/analytics/types`).
 *
 * The window is one of the Analytics presets, **today by default**, resolved
 * by the server in receiver-local time; over "Since T0" the two grouped views
 * are every discrete airframe and every discrete type the receiver has ever
 * heard. A summary line states what the window held — sightings, aircraft,
 * types, never-seen-before — counted live, and each figure switches to the
 * grouping that lists what it counts.
 *
 * Window, grouping, sort, filters and page all persist in the URL. Reuses the
 * Aircraft page's pagination controls — they already handle a `null` total
 * (§2.4's allowance `/sightings` exercises, unlike the two grouped lists,
 * whose totals are exact) by falling back to "a full page came back" as the
 * signal there is a next page.
 */

import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { requireNavItem } from "@/components/shell/nav-items";
import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";
import { PresetSelector } from "@/features/analytics/components/PresetSelector";
import { EmptyResult } from "@/features/history/components/EmptyResult";
import {
  QueryErrorBanner,
  QueryErrorState,
} from "@/features/history/components/QueryError";
import { RefreshStatus } from "@/features/history/components/RefreshStatus";
import { TimezoneNote } from "@/features/history/components/TimezoneNote";
import { LIST_REFRESH_MS } from "@/features/history/lib/refresh";
import { GroupSelector } from "@/features/sightings/components/GroupSelector";
import { WindowSummary } from "@/features/sightings/components/WindowSummary";
import { useSightingsTableState } from "@/features/sightings/hooks/useSightingsTableState";
import {
  PAGE_SIZE,
  type SightingsGroup,
} from "@/features/sightings/lib/urlState";
import { SeenAircraftTable } from "@/features/sightings/SeenAircraftTable";
import { SeenTypesTable } from "@/features/sightings/SeenTypesTable";
import { SightingsFilters } from "@/features/sightings/SightingsFilters";
import { SightingsTable } from "@/features/sightings/SightingsTable";
import {
  useAnalyticsCountsQuery,
  useAnalyticsSeenAircraftQuery,
  useAnalyticsSeenTypesQuery,
} from "@/lib/api/analytics";
import { useReceiverQuery } from "@/lib/api/receiver";
import {
  useSightingListQuery,
  type SightingSortKey,
} from "@/lib/api/sightings";

const item = requireNavItem("/sightings");

/** What a list query exposes to the shared loading/error/empty frame. */
interface ListQueryLike {
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
  isPlaceholderData: boolean;
  error: Error | null;
  refetch: () => unknown;
}

interface ListFrameProps {
  query: ListQueryLike;
  /** `undefined` until the first page has arrived. */
  rowCount: number | undefined;
  /** "the sightings log", "the aircraft list" — names the thing in messages. */
  what: string;
  loadingLabel: string;
  emptyMessage: string;
  page: number;
  onBackToFirstPage: () => void;
  children: ReactNode;
}

/** The loading / failed / empty / populated frame all three groupings share,
 * so each behaves the same way around its own table: the table stays on
 * screen behind a failed refetch (review R2-04), and an empty page past the
 * first offers the way back. */
function ListFrame({
  query,
  rowCount,
  what,
  loadingLabel,
  emptyMessage,
  page,
  onBackToFirstPage,
  children,
}: ListFrameProps) {
  if (query.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {loadingLabel}
      </p>
    );
  }
  if (rowCount === undefined) {
    return (
      <QueryErrorState
        message={`Could not load ${what}: ${query.error?.message ?? "the request failed"}`}
        onRetry={() => void query.refetch()}
        isRetrying={query.isFetching}
      />
    );
  }
  return (
    <>
      {query.isError && (
        <QueryErrorBanner
          message={`Could not refresh ${what}: ${query.error?.message ?? "the request failed"}.`}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}
      {rowCount === 0 ? (
        <EmptyResult
          message={emptyMessage}
          page={page}
          onBackToFirstPage={onBackToFirstPage}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          {children}
        </div>
      )}
    </>
  );
}

export function SightingsPage() {
  const { state, setState } = useSightingsTableState();
  const receiverQuery = useReceiverQuery();
  const { preset, group } = state;
  const offset = (state.page - 1) * PAGE_SIZE;
  // Page 1 only, as on `/aircraft` (`features/history/lib/refresh.ts`).
  const refetchInterval = state.page === 1 ? LIST_REFRESH_MS : false;

  const countsQuery = useAnalyticsCountsQuery(
    { preset },
    { refetchInterval: LIST_REFRESH_MS },
  );
  // Only the grouping on screen asks for its page; the other two wait.
  const listQuery = useSightingListQuery(
    {
      limit: PAGE_SIZE,
      offset,
      sort: state.sort,
      order: state.order,
      icao: state.icao,
      q: state.q,
      preset,
      open: state.open ? true : undefined,
    },
    { refetchInterval, enabled: group === "sightings" },
  );
  const aircraftQuery = useAnalyticsSeenAircraftQuery(
    { preset, limit: PAGE_SIZE, offset, type: state.type },
    { refetchInterval, enabled: group === "aircraft" },
  );
  const typesQuery = useAnalyticsSeenTypesQuery(
    { preset, limit: PAGE_SIZE, offset },
    { refetchInterval, enabled: group === "types" },
  );
  const activeQuery =
    group === "sightings"
      ? listQuery
      : group === "aircraft"
        ? aircraftQuery
        : typesQuery;

  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  function handleSortChange(key: SightingSortKey) {
    if (key === state.sort) {
      setState({ order: state.order === "asc" ? "desc" : "asc" });
    } else {
      setState({ sort: key, order: "desc" });
    }
  }

  function handleGroupChange(next: SightingsGroup) {
    // The type filter belongs to the aircraft grouping; leaving it for the
    // log or the type list drops it rather than hiding an active filter.
    setState(
      next === "aircraft" ? { group: next } : { group: next, type: undefined },
    );
  }

  function showAircraftOfType(type: string) {
    setState({ group: "aircraft", type });
  }

  return (
    <div className="flex h-full flex-col px-4 py-6 md:px-8">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {item.label}
          </h1>
          <p className="text-sm text-muted-foreground">{item.description}</p>
          <TimezoneNote className="mt-1" timezone={timezone} />
          <RefreshStatus
            className="mt-1"
            updatedAt={activeQuery.dataUpdatedAt}
            isFetching={activeQuery.isFetching}
            onRefresh={() => {
              void activeQuery.refetch();
              void countsQuery.refetch();
            }}
            intervalMs={refetchInterval === false ? null : refetchInterval}
          />
        </div>
        <PresetSelector
          preset={preset}
          onChange={(next) => setState({ preset: next })}
        />
      </header>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <WindowSummary
          counts={countsQuery.data}
          isLoading={countsQuery.isPending}
          isError={countsQuery.isError}
          group={group}
          onGroupChange={handleGroupChange}
        />
        <GroupSelector group={group} onChange={handleGroupChange} />
      </div>

      {group === "sightings" && (
        <>
          <SightingsFilters state={state} onChange={setState} />
          <ListFrame
            query={listQuery}
            rowCount={listQuery.data?.items.length}
            what="the sightings log"
            loadingLabel="Loading sightings…"
            emptyMessage="No sightings match this window and these filters."
            page={state.page}
            onBackToFirstPage={() => setState({ page: 1 })}
          >
            <SightingsTable
              rows={listQuery.data?.items ?? []}
              sort={state.sort}
              order={state.order}
              onSortChange={handleSortChange}
              units={units}
              timezone={timezone}
              refreshing={listQuery.isFetching && listQuery.isPlaceholderData}
            />
            <AircraftPaginationControls
              page={state.page}
              pageSize={PAGE_SIZE}
              rowCount={listQuery.data?.items.length ?? 0}
              total={listQuery.data?.total ?? null}
              noun={{ singular: "sighting", plural: "sightings" }}
              onPageChange={(page) => setState({ page })}
            />
          </ListFrame>
        </>
      )}

      {group === "aircraft" && (
        <>
          {state.type !== undefined && (
            <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">Showing only</span>
              <span className="rounded-full border border-border bg-card px-2 py-0.5 font-mono">
                {state.type}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                onClick={() => setState({ type: undefined })}
              >
                Show all types
              </Button>
            </div>
          )}
          <ListFrame
            query={aircraftQuery}
            rowCount={aircraftQuery.data?.items.length}
            what="the aircraft list"
            loadingLabel="Loading aircraft…"
            emptyMessage={
              state.type === undefined
                ? "No aircraft were heard in this window."
                : `No ${state.type} aircraft were heard in this window.`
            }
            page={state.page}
            onBackToFirstPage={() => setState({ page: 1 })}
          >
            <SeenAircraftTable
              rows={aircraftQuery.data?.items ?? []}
              timezone={timezone}
              onTypeSelect={showAircraftOfType}
              refreshing={
                aircraftQuery.isFetching && aircraftQuery.isPlaceholderData
              }
            />
            <AircraftPaginationControls
              page={state.page}
              pageSize={PAGE_SIZE}
              rowCount={aircraftQuery.data?.items.length ?? 0}
              total={aircraftQuery.data?.total ?? null}
              noun={{ singular: "aircraft", plural: "aircraft" }}
              onPageChange={(page) => setState({ page })}
            />
          </ListFrame>
        </>
      )}

      {group === "types" && (
        <ListFrame
          query={typesQuery}
          rowCount={typesQuery.data?.items.length}
          what="the type list"
          loadingLabel="Loading types…"
          emptyMessage="No aircraft with a known type were heard in this window."
          page={state.page}
          onBackToFirstPage={() => setState({ page: 1 })}
        >
          <SeenTypesTable
            rows={typesQuery.data?.items ?? []}
            timezone={timezone}
            onTypeSelect={showAircraftOfType}
            refreshing={typesQuery.isFetching && typesQuery.isPlaceholderData}
          />
          <AircraftPaginationControls
            page={state.page}
            pageSize={PAGE_SIZE}
            rowCount={typesQuery.data?.items.length ?? 0}
            total={typesQuery.data?.total ?? null}
            noun={{ singular: "type", plural: "types" }}
            onPageChange={(page) => setState({ page })}
          />
        </ListFrame>
      )}
    </div>
  );
}
