import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { FieldRow } from "@/features/aircraft-detail/components/FieldRow";
import { formatDistance } from "@/features/aircraft-detail/lib/format";
import type { UnitSystem } from "@/lib/api/config";
import type { NearestAirportInfo } from "@/lib/api/live";

/**
 * The nearest-airport section — SPEC §41, `docs/API.md` §3.3.
 *
 * A section of its own rather than three rows inside Route, because SPEC §41
 * requires arrival/departure status to be *"clearly labeled as inferred"* and
 * the roadmap's acceptance criterion is that inference and external route data
 * are **visually and semantically distinct**. Three things carry that here:
 *
 * 1. A separate `DetailSection`, so the two never share a heading.
 * 2. A standing caption under the heading saying what this section is. It is
 *    there whether or not a phase was inferred, so the label describes the
 *    section rather than appearing only when there is a guess to excuse.
 * 3. The phase rendered as a text badge reading `Likely arriving · inferred`,
 *    with the hedge in the words. SPEC §80 forbids color-only signalling, so
 *    the badge's tint is decoration and its text is the message.
 *
 * The section renders whether or not there is an airport: an aircraft at
 * cruise gets `Unknown`, which is what the panel says about every other
 * absent optional value (`docs/API.md` §2.7). Showing nothing would make the
 * panel's shape depend on altitude for no gain.
 */

const PHASE_LABELS: Record<NonNullable<NearestAirportInfo["phase"]>, string> = {
  arriving: "Likely arriving",
  departing: "Likely departing",
};

interface NearestAirportSectionProps {
  airport: NearestAirportInfo | null;
  /** `provenance.nearest_airport`, which the backend sets to `heuristic`
   * whenever the block is present. Passed through rather than hard-coded so
   * the dot and its tooltip describe what the payload actually said. */
  provenanceSource: string | undefined;
  units: UnitSystem;
}

function PhaseBadge({
  phase,
}: {
  phase: NonNullable<NearestAirportInfo["phase"]>;
}) {
  return (
    <span className="rounded border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-xs font-medium">
      {PHASE_LABELS[phase]} · inferred
    </span>
  );
}

export function NearestAirportSection({
  airport,
  provenanceSource,
  units,
}: NearestAirportSectionProps) {
  return (
    <DetailSection title="Nearest airport">
      <p className="pb-1 text-xs italic text-muted-foreground">
        Inferred by FlightSite from altitude, vertical rate and distance — not a
        reported route.
      </p>
      <FieldRow
        label="Airport"
        value={airport === null ? null : `${airport.ident} — ${airport.name}`}
        provenanceSource={provenanceSource}
      />
      <FieldRow
        label="Distance"
        value={
          airport === null ? null : formatDistance(airport.distance_nm, units)
        }
        provenanceSource={provenanceSource}
      />
      <FieldRow
        label="Phase"
        value={
          airport === null || airport.phase === null ? null : (
            <PhaseBadge phase={airport.phase} />
          )
        }
        provenanceSource={provenanceSource}
      />
    </DetailSection>
  );
}
