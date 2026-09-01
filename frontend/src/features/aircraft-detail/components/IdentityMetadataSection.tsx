/**
 * The "Identity & metadata" section — shared by the live detail panel
 * (fed from the WebSocket's §3.3 aircraft object) and the non-live detail
 * page (fed from `GET /api/v1/aircraft/{icao}`, roadmap slice 029). Both
 * payload shapes carry these six fields under the same names, so one
 * component renders either without either caller needing to reshape its data
 * first.
 */

import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { FieldRow } from "@/features/aircraft-detail/components/FieldRow";
import { classificationSummary } from "@/features/aircraft-detail/lib/classificationSummary";
import type { Classification } from "@/lib/api/live";

/** The subset of the live and historical aircraft shapes this section reads.
 * `LiveAircraft` and the Aircraft page's `AircraftListRow`/`AircraftDetail`
 * types all satisfy this structurally. */
export interface AircraftIdentityMetadata {
  registration: string | null;
  aircraft_type: string | null;
  model: string | null;
  operator: string | null;
  operator_group: string | null;
  classification: Classification | null;
  provenance: Record<string, string>;
}

export interface IdentityMetadataSectionProps {
  aircraft: AircraftIdentityMetadata;
}

export function IdentityMetadataSection({
  aircraft,
}: IdentityMetadataSectionProps) {
  return (
    <DetailSection title="Identity & metadata">
      <FieldRow
        label="Registration"
        value={aircraft.registration}
        provenanceSource={aircraft.provenance.registration ?? "decoder"}
      />
      <FieldRow
        label="Type"
        value={aircraft.aircraft_type}
        provenanceSource={aircraft.provenance.aircraft_type ?? "decoder"}
      />
      <FieldRow
        label="Model"
        value={aircraft.model}
        provenanceSource={aircraft.provenance.model ?? "decoder"}
      />
      <FieldRow
        label="Operator"
        value={aircraft.operator}
        provenanceSource={aircraft.provenance.operator ?? "decoder"}
      />
      <FieldRow
        label="Operator group"
        value={aircraft.operator_group}
        provenanceSource={aircraft.provenance.operator_group ?? "decoder"}
      />
      <FieldRow
        label="Classification"
        value={classificationSummary(aircraft.classification)}
        provenanceSource={aircraft.provenance.classification ?? "decoder"}
      />
    </DetailSection>
  );
}
