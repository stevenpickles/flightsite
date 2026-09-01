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
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiV1Error, useAircraftDetailQuery } from "@/lib/api/aircraft";
import { useReceiverQuery } from "@/lib/api/receiver";

const ICAO_PATTERN = /^[0-9a-f]{6}$/;

export function AircraftDetailPage() {
  const { icao: rawIcao } = useParams<{ icao: string }>();
  const icao = rawIcao?.toLowerCase();
  const validIcao = icao !== undefined && ICAO_PATTERN.test(icao);

  const detailQuery = useAircraftDetailQuery(validIcao ? icao : undefined);
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

  if (detailQuery.isError) {
    const notFound =
      detailQuery.error instanceof ApiV1Error &&
      detailQuery.error.status === 404;
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <h1 className="text-lg font-semibold">
          {notFound ? "Aircraft not found" : "Could not load this aircraft"}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {notFound
            ? `This receiver has never sighted ${icao.toUpperCase()}.`
            : detailQuery.error.message}
        </p>
      </div>
    );
  }

  const detail = detailQuery.data;
  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  return (
    <TooltipProvider delayDuration={200}>
      <div className="mx-auto max-w-2xl px-4 py-6">
        <header className="border-b border-border pb-4">
          <h1 className="text-lg font-semibold">
            {detail.registration ?? detail.icao.toUpperCase()}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            ICAO {detail.icao.toUpperCase()} · Registration{" "}
            {detail.registration ?? <UnknownValue />}
          </p>
          {detail.live && <LiveMapJumpLink icao={detail.icao} />}
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
