/**
 * Plain-language labels for the sighting event timeline (SPEC §52) — one
 * entry per `docs/DATA_MODEL.md` §2.5 event type, including the enrichment
 * and emergency events the task specifically calls out.
 */

import type { SightingEvent } from "@/lib/api/sightings";

export interface EventDescription {
  label: string;
  detail: string | null;
}

function stringDetail(
  detail: Record<string, string | null> | null,
  key: string,
): string | null {
  const value = detail?.[key];
  return value ?? null;
}

export function describeSightingEvent(event: SightingEvent): EventDescription {
  const { type, detail } = event;
  switch (type) {
    case "callsign_change": {
      const from = stringDetail(detail, "from");
      const to = stringDetail(detail, "to");
      return {
        label: "Callsign changed",
        detail: from !== null && to !== null ? `${from} → ${to}` : to,
      };
    }
    case "squawk_change": {
      const from = stringDetail(detail, "from");
      const to = stringDetail(detail, "to");
      return {
        label: "Squawk changed",
        detail: from !== null && to !== null ? `${from} → ${to}` : to,
      };
    }
    case "emergency_start": {
      const squawk = stringDetail(detail, "squawk");
      return {
        label: "Emergency declared",
        detail: squawk === null ? null : `Squawk ${squawk}`,
      };
    }
    case "emergency_end": {
      const squawk = stringDetail(detail, "squawk");
      return {
        label: "Emergency cleared",
        detail: squawk === null ? null : `Squawk ${squawk}`,
      };
    }
    case "route_enriched": {
      const origin = stringDetail(detail, "origin");
      const destination = stringDetail(detail, "destination");
      const source = stringDetail(detail, "source");
      const route =
        origin !== null || destination !== null
          ? `${origin ?? "?"} → ${destination ?? "?"}`
          : null;
      return {
        label: "Route enriched",
        detail:
          [route, source].filter((part) => part !== null).join(" · ") || null,
      };
    }
    case "classification_available":
      return { label: "Classification became available", detail: null };
    case "alert_matched":
      return { label: "Alert matched", detail: null };
    case "alert_severity_upgraded":
      return { label: "Alert severity upgraded", detail: null };
    default:
      // Exhaustive by the vocabulary's Literal union; a future event type the
      // client hasn't learned yet still renders something rather than
      // crashing the timeline.
      return { label: type, detail: null };
  }
}
