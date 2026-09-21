/**
 * The non-live aircraft detail route — `/aircraft/:icao` (roadmap slice
 * 029). The panel (`AircraftDetailPanel`) only ever shows an aircraft
 * currently in the live picture; this route shows *any* aircraft the
 * receiver has ever sighted, fed by `GET /api/v1/aircraft/{icao}` rather
 * than the WebSocket. It reuses the same field components the panel uses
 * (`IdentityMetadataSection`, `FieldRow`, `ExternalTrackerLinks`) so the two
 * views read identically wherever they show the same fact, and adds the one
 * section the panel cannot: `LifetimeSection`'s SPEC §53 records.
 */

import { useParams } from "react-router-dom";

import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { ExternalTrackerLinks } from "@/features/aircraft-detail/components/ExternalTrackerLinks";
import { FieldRow } from "@/features/aircraft-detail/components/FieldRow";
import { IdentityMetadataSection } from "@/features/aircraft-detail/components/IdentityMetadataSection";
import { LifetimeSection } from "@/features/aircraft-detail/components/LifetimeSection";
import { LiveMapJumpLink } from "@/features/aircraft-detail/components/LiveMapJumpLink";
import { RecentSightingsSection } from "@/features/aircraft-detail/components/RecentSightingsSection";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import {
  QueryErrorBanner,
  QueryErrorState,
} from "@/features/history/components/QueryError";
import { RefreshStatus } from "@/features/history/components/RefreshStatus";
import { DETAIL_REFRESH_MS } from "@/features/history/lib/refresh";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiV1Error, useAircraftDetailQuery } from "@/lib/api/aircraft";
import { useReceiverQuery } from "@/lib/api/receiver";

const ICAO_PATTERN = /^[0-9a-f]{6}$/;

export function AircraftDetailPage() {
  const { icao: rawIcao } = useParams<{ icao: string }>();
  const icao = rawIcao?.toLowerCase();
  const validIcao = icao !== undefined && ICAO_PATTERN.test(icao);

  // The cadence applies only while the airframe is in the live picture —
  // that is the one state in which its lifetime block is still changing
  // (review R2-03); the hook itself enforces the condition, since only it can
  // see the payload the condition reads.
  const detailQuery = useAircraftDetailQuery(validIcao ? icao : undefined, {
    refetchInterval: DETAIL_REFRESH_MS,
  });
  const receiverQuery = useReceiverQuery();

  if (!validIcao) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <h1 className="text-lg font-semibold">Aircraft not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          &ldquo;{rawIcao}&rdquo; is not a valid ICAO 24-bit address.
        </p>
      </div>
    );
  }

  if (detailQuery.isPending) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="text-sm text-muted-foreground">Loading aircraft…</p>
      </div>
    );
  }

  // Only when nothing has ever loaded: a failure behind a rendered page
  // becomes a banner further down, so a transient hiccup on a page the user
  // is reading does not replace what they were reading (review R2-04).
  const detail = detailQuery.data;
  if (detail === undefined) {
    const notFound =
      detailQuery.error instanceof ApiV1Error &&
      detailQuery.error.status === 404;
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        {notFound ? (
          <>
            <h1 className="text-lg font-semibold">Aircraft not found</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              This receiver has never sighted {icao.toUpperCase()}.
            </p>
          </>
        ) : (
          <>
            <h1 className="mb-3 text-lg font-semibold">
              Could not load this aircraft
            </h1>
            <QueryErrorState
              message={
                detailQuery.error?.message ??
                `The request for ${icao.toUpperCase()} failed.`
              }
              onRetry={() => void detailQuery.refetch()}
              isRetrying={detailQuery.isFetching}
            />
          </>
        )}
      </div>
    );
  }

  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  return (
    <TooltipProvider delayDuration={200}>
      <div className="mx-auto max-w-2xl px-4 py-6">
        {detailQuery.isError && (
          <QueryErrorBanner
            message={`Could not refresh this aircraft: ${detailQuery.error.message}.`}
            onRetry={() => void detailQuery.refetch()}
            isRetrying={detailQuery.isFetching}
          />
        )}
        <header className="border-b border-border pb-4">
          <h1 className="text-lg font-semibold">
            {detail.registration ?? detail.icao.toUpperCase()}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            ICAO {detail.icao.toUpperCase()} · Registration{" "}
            {detail.registration ?? <UnknownValue />}
          </p>
          {detail.live && <LiveMapJumpLink icao={detail.icao} />}
          <RefreshStatus
            className="mt-2"
            updatedAt={detailQuery.dataUpdatedAt}
            isFetching={detailQuery.isFetching}
            onRefresh={() => void detailQuery.refetch()}
            intervalMs={detail.live ? DETAIL_REFRESH_MS : null}
          />
        </header>

        <IdentityMetadataSection aircraft={detail} />

        <DetailSection title="Manufacture & ownership">
          <FieldRow
            label="Manufacture year"
            value={
              detail.manufacture_year === null
                ? null
                : String(detail.manufacture_year)
            }
            provenanceSource={detail.provenance.manufacture_year ?? "decoder"}
          />
          <FieldRow
            label="Owner"
            value={detail.owner}
            provenanceSource={detail.provenance.owner ?? "decoder"}
          />
        </DetailSection>

        <LifetimeSection
          lifetime={detail.lifetime}
          units={units}
          timezone={timezone}
        />

        <RecentSightingsSection icao={detail.icao} timezone={timezone} />

        <DetailSection title="External trackers">
          <ExternalTrackerLinks
            aircraft={{
              icao: detail.icao,
              callsign: null,
              registration: detail.registration,
            }}
          />
        </DetailSection>
      </div>
    </TooltipProvider>
  );
}
