/**
 * The Aircraft page (roadmap slice 029, SPEC §56): every aircraft this
 * receiver has ever sighted, sorted and paginated server-side via
 * `GET /api/v1/aircraft`, with sort/page persisted in the URL. Rows open
 * the non-live aircraft detail route (`AircraftDetailPage`).
 */

import { requireNavItem } from "@/components/shell/nav-items";
import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";
import { AircraftTable } from "@/features/aircraft-page/AircraftTable";
import { useAircraftTableState } from "@/features/aircraft-page/hooks/useAircraftTableState";
import { PAGE_SIZE } from "@/features/aircraft-page/lib/urlState";
import { useAircraftListQuery, type AircraftSortKey } from "@/lib/api/aircraft";
import { useReceiverQuery } from "@/lib/api/receiver";

const item = requireNavItem("/aircraft");

export function AircraftPage() {
  const { state, setState } = useAircraftTableState();
  const receiverQuery = useReceiverQuery();
  const listQuery = useAircraftListQuery({
    limit: PAGE_SIZE,
    offset: (state.page - 1) * PAGE_SIZE,
    sort: state.sort,
    order: state.order,
  });

  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  function handleSortChange(key: AircraftSortKey) {
    if (key === state.sort) {
      setState({ order: state.order === "asc" ? "desc" : "asc" });
    } else {
      // A freshly-chosen column starts in the direction that shows the
      // most interesting rows first: newest/most/closest before
      // oldest/least/farthest.
      setState({ sort: key, order: "desc" });
    }
  }

  return (
    <div className="flex h-full flex-col px-4 py-6 md:px-8">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight">{item.label}</h1>
        <p className="text-sm text-muted-foreground">{item.description}</p>
      </header>

      {listQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading aircraft…</p>
      ) : listQuery.isError ? (
        <p className="text-sm text-destructive">
          Could not load the aircraft list: {listQuery.error.message}
        </p>
      ) : listQuery.data.items.length === 0 && state.page === 1 ? (
        <p className="text-sm text-muted-foreground">
          This receiver hasn&rsquo;t sighted any aircraft yet.
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <AircraftTable
            rows={listQuery.data.items}
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
            rowCount={listQuery.data.items.length}
            total={listQuery.data.total}
            onPageChange={(page) => setState({ page })}
          />
        </div>
      )}
    </div>
  );
}
