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
import { formatReceiverLocalDateTime } from "@/features/aircraft-detail/lib/format";
import {
  SightingReceptionSection,
  SightingRecordsSection,
  SightingRouteSection,
} from "@/features/sighting-detail/SightingDetailSections";
import { SightingEventsTimeline } from "@/features/sighting-detail/SightingEventsTimeline";
import { SightingPathMap } from "@/features/sighting-detail/SightingPathMap";
import { ClosureReasonTooltip } from "@/features/sightings/components/ClosureReasonTooltip";
import { formatSightingDuration } from "@/features/sightings/lib/format";
import { useAircraftDetailQuery } from "@/lib/api/aircraft";
import { useReceiverQuery } from "@/lib/api/receiver";
import { SightingsApiError, useSightingDetailQuery } from "@/lib/api/sightings";

export function SightingDetailPage() {
  const { id: rawId } = useParams<{ id: string }>();
  const id =
    rawId !== undefined && /^\d+$/.test(rawId) ? Number(rawId) : undefined;

  const detailQuery = useSightingDetailQuery(id);
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

  if (detailQuery.isError) {
    const notFound =
      detailQuery.error instanceof SightingsApiError &&
      detailQuery.error.status === 404;
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <h1 className="text-lg font-semibold">
          {notFound ? "Sighting not found" : "Could not load this sighting"}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {notFound
            ? `No sighting exists with id ${id}.`
            : detailQuery.error.message}
        </p>
      </div>
    );
  }

  const sighting = detailQuery.data;
  const aircraft = aircraftQuery.data;
  const isOpen = sighting.ended_at === null;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="mx-auto max-w-3xl px-4 py-6">
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
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Started</dt>
              <dd>
                {formatReceiverLocalDateTime(sighting.started_at, timezone)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Ended</dt>
              <dd>
                {isOpen ? (
                  <span className="font-medium text-accent">Ongoing</span>
                ) : (
                  formatReceiverLocalDateTime(
                    sighting.ended_at as string,
                    timezone,
                  )
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Duration</dt>
              <dd>
                {sighting.duration_s === null ? (
                  <UnknownValue />
                ) : (
                  formatSightingDuration(sighting.duration_s)
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Closure</dt>
              <dd>
                {sighting.closure_reason === null ? (
                  <UnknownValue />
                ) : (
                  <ClosureReasonTooltip reason={sighting.closure_reason} />
                )}
              </dd>
            </div>
          </dl>
        </header>

        <DetailSection title="Path">
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
