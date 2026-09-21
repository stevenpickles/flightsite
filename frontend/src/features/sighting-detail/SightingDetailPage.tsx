/**
 * The sighting detail route — `/sightings/:id` (roadmap slice 030). Summary
 * header (aircraft identity linking to `/aircraft/:icao`, times, duration,
 * closure), the simplified path on a map, the event timeline, reception
 * stats and the route block.
 */

import { Link, useParams } from "react-router-dom";

import { TooltipProvider } from "@/components/ui/tooltip";
import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { ReceiverTime } from "@/features/aircraft-detail/components/ReceiverTime";
import {
  SightingReceptionSection,
  SightingRecordsSection,
  SightingRouteSection,
} from "@/features/sighting-detail/SightingDetailSections";
import { describePathSample } from "@/features/sighting-detail/lib/pathSample";
import { SightingEventsTimeline } from "@/features/sighting-detail/SightingEventsTimeline";
import { SightingPathMap } from "@/features/sighting-detail/SightingPathMap";
import {
  QueryErrorBanner,
  QueryErrorState,
} from "@/features/history/components/QueryError";
import { RefreshStatus } from "@/features/history/components/RefreshStatus";
import { TimezoneNote } from "@/features/history/components/TimezoneNote";
import { DETAIL_REFRESH_MS } from "@/features/history/lib/refresh";
import { ClosureReasonTooltip } from "@/features/sightings/components/ClosureReasonTooltip";
import {
  formatOpenSightingDuration,
  formatSightingDuration,
} from "@/features/sightings/lib/format";
import { useAircraftDetailQuery } from "@/lib/api/aircraft";
import { useReceiverQuery } from "@/lib/api/receiver";
import { SightingsApiError, useSightingDetailQuery } from "@/lib/api/sightings";

export function SightingDetailPage() {
  const { id: rawId } = useParams<{ id: string }>();
  const id =
    rawId !== undefined && /^\d+$/.test(rawId) ? Number(rawId) : undefined;

  // The cadence applies only while the sighting is open — see
  // `useSightingDetailQuery` (review R2-03).
  const detailQuery = useSightingDetailQuery(id, {
    refetchInterval: DETAIL_REFRESH_MS,
  });
  const receiverQuery = useReceiverQuery();
  // Best-effort: adds a registration/type to the header when it resolves,
  // but the page is fully usable from the sighting payload alone (it always
  // carries the ICAO, which is enough to link to `/aircraft/:icao`).
  const aircraftQuery = useAircraftDetailQuery(detailQuery.data?.icao);

  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  if (id === undefined) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <h1 className="text-lg font-semibold">Sighting not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          &ldquo;{rawId}&rdquo; is not a valid sighting id.
        </p>
      </div>
    );
  }

  if (detailQuery.isPending) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="text-sm text-muted-foreground">Loading sighting…</p>
      </div>
    );
  }

  // Only when nothing has ever loaded (review R2-04); a failure behind a
  // rendered sighting becomes a banner below instead.
  const sighting = detailQuery.data;
  if (sighting === undefined) {
    const notFound =
      detailQuery.error instanceof SightingsApiError &&
      detailQuery.error.status === 404;
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        {notFound ? (
          <>
            <h1 className="text-lg font-semibold">Sighting not found</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              No sighting exists with id {id}.
            </p>
          </>
        ) : (
          <>
            <h1 className="mb-3 text-lg font-semibold">
              Could not load this sighting
            </h1>
            <QueryErrorState
              message={
                detailQuery.error?.message ??
                `The request for sighting ${id} failed.`
              }
              onRetry={() => void detailQuery.refetch()}
              isRetrying={detailQuery.isFetching}
            />
          </>
        )}
      </div>
    );
  }

  const aircraft = aircraftQuery.data;
  const isOpen = sighting.ended_at === null;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="mx-auto max-w-3xl px-4 py-6">
        {detailQuery.isError && (
          <QueryErrorBanner
            message={`Could not refresh this sighting: ${detailQuery.error.message}.`}
            onRetry={() => void detailQuery.refetch()}
            isRetrying={detailQuery.isFetching}
          />
        )}
        <header className="border-b border-border pb-4">
          <h1 className="text-lg font-semibold">
            <Link
              to={`/aircraft/${sighting.icao}`}
              className="text-accent hover:underline"
            >
              {aircraft?.registration ??
                sighting.callsign ??
                sighting.icao.toUpperCase()}
            </Link>
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            ICAO {sighting.icao.toUpperCase()}
            {sighting.callsign !== null && <> · Callsign {sighting.callsign}</>}
            {sighting.squawk !== null && <> · Squawk {sighting.squawk}</>}
          </p>
          <TimezoneNote className="mt-2" timezone={timezone} />
          <RefreshStatus
            className="mt-2"
            updatedAt={detailQuery.dataUpdatedAt}
            isFetching={detailQuery.isFetching}
            onRefresh={() => void detailQuery.refetch()}
            intervalMs={isOpen ? DETAIL_REFRESH_MS : null}
          />
          {/* One column on a phone: two 134px columns are what printed
           * "Ended Ongoing" off the right edge in the review's 390px
           * capture (R2-08). */}
          <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Started</dt>
              <dd>
                <ReceiverTime iso={sighting.started_at} timezone={timezone} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Ended</dt>
              <dd>
                {isOpen ? (
                  <span className="font-medium text-accent">Ongoing</span>
                ) : (
                  <ReceiverTime
                    iso={sighting.ended_at as string}
                    timezone={timezone}
                  />
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Duration</dt>
              <dd>
                {/* A sighting this page calls "Ongoing" two cells to the
                 * left must not have an `Unknown` duration: both ends are
                 * known, and one of them is now (review R2-02). */}
                {isOpen ? (
                  <span className="text-accent">
                    {formatOpenSightingDuration(sighting.elapsed_s)}
                  </span>
                ) : sighting.duration_s === null ? (
                  <UnknownValue />
                ) : (
                  formatSightingDuration(sighting.duration_s)
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Closure</dt>
              <dd>
                {/* Nothing closed it because nothing has closed it yet —
                 * "Still open", not `Unknown` (review R2-02). */}
                {isOpen ? (
                  <span className="text-muted-foreground">Still open</span>
                ) : sighting.closure_reason === null ? (
                  <UnknownValue />
                ) : (
                  <ClosureReasonTooltip reason={sighting.closure_reason} />
                )}
              </dd>
            </div>
          </dl>
        </header>

        {/* The drawn line is a sample, and the page used to say so nowhere:
         * "Path" beside "Position reports 543" with eleven vertices on
         * screen left a reader to conclude one of the two numbers was wrong
         * (review R2-12). Simplification is correct for a closed sighting
         * (SPEC §19); for an open one this is the crash-recovery checkpoint
         * tail, which is why the two are named differently. */}
        <DetailSection
          title={isOpen ? "Path (checkpointed)" : "Path (simplified)"}
          description={describePathSample(
            sighting.path.length,
            sighting.reception.position_count,
            isOpen,
          )}
        >
          <SightingPathMap path={sighting.path} />
        </DetailSection>

        <SightingRouteSection
          route={sighting.route}
          provenanceSource={sighting.provenance.route}
        />

        <DetailSection title="Events">
          <SightingEventsTimeline
            events={sighting.events}
            timezone={timezone}
          />
        </DetailSection>

        <SightingReceptionSection reception={sighting.reception} />

        <SightingRecordsSection records={sighting.records} units={units} />
      </div>
    </TooltipProvider>
  );
}
