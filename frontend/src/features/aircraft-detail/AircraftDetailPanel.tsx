/**
 * Aircraft detail panel (roadmap slice 016).
 *
 * Opens whenever `useLiveAircraftStore.selectedIcao` is set — selection
 * itself is wired by `features/map/aircraft/useAircraftLayer.ts` (map
 * clicks) and is out of this slice's scope; this component only reads the
 * selection and the record it names. It is a persistent side panel, not a
 * modal: the map stays interactive and visible behind it (SPEC §50 asks for
 * "comprehensive detail" without saying the map should be hidden to show
 * it), so it renders as a right-side sheet on desktop and a bottom sheet on
 * small screens, and never covers the full viewport.
 *
 * A selected aircraft that has since departed the live picture (faded into
 * `departing`, or aged out of that fade entirely) still renders — the panel
 * shows its last known values rather than snapping shut, since a user who
 * opened it to watch an aircraft land or go stale still wants to see where
 * it ended up. Only an explicit close/Escape/re-click-elsewhere clears the
 * selection.
 */

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { EmergencySquawkBadge } from "@/features/aircraft-detail/components/EmergencySquawkBadge";
import { ExternalTrackerLinks } from "@/features/aircraft-detail/components/ExternalTrackerLinks";
import { FieldRow } from "@/features/aircraft-detail/components/FieldRow";
import { PositionSourceBadge } from "@/features/aircraft-detail/components/PositionSourceBadge";
import { ReservedSectionRow } from "@/features/aircraft-detail/components/ReservedSectionRow";
import { TrackStats } from "@/features/aircraft-detail/components/TrackStats";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import {
  formatAltitude,
  formatDegreesWithCardinal,
  formatDistance,
  formatMessageCount,
  formatOnGround,
  formatReceiverLocalTime,
  formatRssi,
  formatSpeed,
  formatVerticalRate,
  isEmergencySquawk,
  verticalTrend,
} from "@/features/aircraft-detail/lib/format";
import { useRelativeAge } from "@/features/aircraft-detail/lib/useRelativeAge";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { LiveAircraft } from "@/lib/api/live";
import { cn } from "@/lib/utils";

/** Vertical-rate direction glyph. Text/symbol-first (▲/▼/—), not a bare
 * color change, per §80. */
const TREND_GLYPH: Record<"climb" | "descend" | "level", string> = {
  climb: "▲",
  descend: "▼",
  level: "—",
};

function classificationSummary(
  classification: LiveAircraft["classification"],
): string | null {
  if (classification === null) {
    return null;
  }
  const flags: string[] = [];
  if (classification.military) flags.push("Military");
  if (classification.government) flags.push("Government");
  if (classification.law_enforcement) flags.push("Law enforcement");
  const base = flags.length > 0 ? flags.join(", ") : "Civilian";
  return classification.mission ? `${base} · ${classification.mission}` : base;
}

export function AircraftDetailPanel() {
  const selectedIcao = useLiveAircraftStore((state) => state.selectedIcao);
  const record = useLiveAircraftStore((state) =>
    state.selectedIcao ? state.aircraft[state.selectedIcao] : undefined,
  );
  const departing = useLiveAircraftStore((state) =>
    state.selectedIcao ? state.departing[state.selectedIcao] : undefined,
  );
  const receiver = useLiveAircraftStore((state) => state.receiver);
  const track = useLiveAircraftStore((state) => state.track);
  const selectAircraft = useLiveAircraftStore((state) => state.selectAircraft);

  const panelRef = useRef<HTMLDivElement>(null);
  const isOpen = selectedIcao !== null;

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        selectAircraft(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, selectAircraft]);

  useEffect(() => {
    if (isOpen) {
      panelRef.current?.focus();
    }
  }, [isOpen, selectedIcao]);

  const aircraft = record?.aircraft ?? departing?.aircraft ?? null;
  const units = receiver?.units ?? "aviation";
  const timezone = receiver?.timezone ?? "UTC";
  const relativeAge = useRelativeAge(aircraft?.last_seen ?? null);

  if (!isOpen || selectedIcao === null) {
    return null;
  }

  const headingId = "aircraft-detail-heading";

  return (
    <TooltipProvider delayDuration={200}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="false"
        aria-labelledby={headingId}
        tabIndex={-1}
        data-testid="aircraft-detail-panel"
        className={cn(
          "fixed inset-x-0 bottom-0 z-20 flex max-h-[75vh] flex-col",
          "rounded-t-xl border-t border-border bg-card text-card-foreground shadow-lg",
          "md:inset-y-0 md:right-0 md:left-auto md:top-0 md:bottom-auto md:h-full md:max-h-none",
          "md:w-[400px] md:rounded-t-none md:rounded-l-xl md:border-t-0 md:border-l",
          "outline-none",
        )}
      >
        <header className="flex shrink-0 items-start justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            <h2 id={headingId} className="truncate text-lg font-semibold">
              {aircraft?.callsign ?? selectedIcao.toUpperCase()}
            </h2>
            <p className="text-xs text-muted-foreground">
              ICAO {selectedIcao.toUpperCase()} · Registration{" "}
              {aircraft?.registration ?? <UnknownValue />}
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              {aircraft && (
                <PositionSourceBadge source={aircraft.position_source} />
              )}
              {aircraft && isEmergencySquawk(aircraft.squawk) && (
                <EmergencySquawkBadge squawk={aircraft.squawk} />
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={() => selectAircraft(null)}
            aria-label="Close aircraft detail"
            className="shrink-0 rounded-md p-1.5 text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </header>

        <div className="overflow-y-auto">
          {aircraft === null ? (
            <p className="px-4 py-4 text-sm text-muted-foreground">
              No live data for this aircraft.
            </p>
          ) : (
            <>
              <DetailSection title="Live">
                <FieldRow
                  label="Altitude"
                  value={formatAltitude(aircraft.altitude_ft, units)}
                  provenanceSource={
                    aircraft.provenance.altitude_ft ?? "decoder"
                  }
                />
                <FieldRow
                  label="Ground speed"
                  value={formatSpeed(aircraft.ground_speed_kt, units)}
                  provenanceSource={
                    aircraft.provenance.ground_speed_kt ?? "decoder"
                  }
                />
                <FieldRow
                  label="Track"
                  value={formatDegreesWithCardinal(aircraft.track_deg)}
                  provenanceSource={aircraft.provenance.track_deg ?? "decoder"}
                />
                <FieldRow
                  label="Vertical rate"
                  value={
                    aircraft.vertical_rate_fpm === null ? null : (
                      <span className="inline-flex items-center gap-1">
                        <span aria-hidden="true">
                          {
                            TREND_GLYPH[
                              verticalTrend(aircraft.vertical_rate_fpm) ??
                                "level"
                            ]
                          }
                        </span>
                        {formatVerticalRate(aircraft.vertical_rate_fpm, units)}
                      </span>
                    )
                  }
                  provenanceSource={
                    aircraft.provenance.vertical_rate_fpm ?? "decoder"
                  }
                />
                <FieldRow
                  label="Distance"
                  value={formatDistance(aircraft.distance_nm, units)}
                  provenanceSource={
                    aircraft.provenance.distance_nm ?? "decoder"
                  }
                />
                <FieldRow
                  label="Bearing"
                  value={formatDegreesWithCardinal(aircraft.bearing_deg)}
                  provenanceSource={
                    aircraft.provenance.bearing_deg ?? "decoder"
                  }
                />
                <FieldRow
                  label="Squawk"
                  value={
                    aircraft.squawk === null ? null : (
                      <span className="inline-flex items-center gap-1.5">
                        {aircraft.squawk}
                        {isEmergencySquawk(aircraft.squawk) && (
                          <EmergencySquawkBadge squawk={aircraft.squawk} />
                        )}
                      </span>
                    )
                  }
                />
                <FieldRow
                  label="Signal (RSSI)"
                  value={formatRssi(aircraft.rssi_db)}
                />
                <FieldRow
                  label="Message count"
                  value={formatMessageCount(aircraft.message_count)}
                />
                <FieldRow
                  label="Last seen"
                  value={
                    <span>
                      {relativeAge}{" "}
                      <span className="text-muted-foreground">
                        ({formatReceiverLocalTime(aircraft.last_seen, timezone)}
                        )
                      </span>
                    </span>
                  }
                />
                <FieldRow
                  label="On ground"
                  value={formatOnGround(aircraft.on_ground)}
                />
              </DetailSection>

              <DetailSection title="Identity & metadata">
                <FieldRow
                  label="Registration"
                  value={aircraft.registration}
                  provenanceSource={
                    aircraft.provenance.registration ?? "decoder"
                  }
                />
                <FieldRow
                  label="Type"
                  value={aircraft.aircraft_type}
                  provenanceSource={
                    aircraft.provenance.aircraft_type ?? "decoder"
                  }
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
                  provenanceSource={
                    aircraft.provenance.operator_group ?? "decoder"
                  }
                />
                <FieldRow
                  label="Classification"
                  value={classificationSummary(aircraft.classification)}
                  provenanceSource={
                    aircraft.provenance.classification ?? "decoder"
                  }
                />
              </DetailSection>

              {/* External route only (§2.6). Both rows always render: a
               * route the provider has not answered for is `Unknown`, which
               * is the same thing the panel says about every other optional
               * field, and is what a stock install with enrichment switched
               * off shows for every aircraft. */}
              <DetailSection title="Route">
                <FieldRow
                  label="Origin"
                  value={aircraft.route.origin}
                  provenanceSource={aircraft.provenance.route}
                />
                <FieldRow
                  label="Destination"
                  value={aircraft.route.destination}
                  provenanceSource={aircraft.provenance.route}
                />
              </DetailSection>

              <DetailSection title="Nearest airport">
                <ReservedSectionRow note="Nearest-airport inference arrives with a later slice." />
              </DetailSection>

              <DetailSection title="History">
                <ReservedSectionRow note="Lifetime sighting records arrive once history is stored (a later slice)." />
              </DetailSection>

              <DetailSection title="External trackers">
                <ExternalTrackerLinks aircraft={aircraft} />
              </DetailSection>

              <div className="px-4 py-3">
                <TrackStats track={track} />
              </div>
            </>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}
