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

/** Joins the parts of a detail line, dropping every absent one; `null`
 * rather than an empty string, so a caller never renders a blank line. */
function join(parts: readonly (string | null)[]): string | null {
  const present = parts.filter((part): part is string => part !== null);
  return present.length === 0 ? null : present.join(" · ");
}

/**
 * §2.8's severity ladder, in the words `AlertSeverityBadge` uses so the
 * timeline and the log's Status column say the same thing about the same
 * match. Kept as a local map rather than imported from that component: it is
 * four strings, and reaching into a component for them would make a
 * rendering choice a shared dependency.
 *
 * An unrecognized value passes through verbatim — a future rung of the
 * ladder reads as itself rather than disappearing.
 */
const SEVERITY_LABELS: Record<string, string> = {
  info: "Info",
  interesting: "Interesting",
  high: "High",
  critical: "Critical",
};

function severityLabel(value: string | null): string | null {
  return value === null ? null : (SEVERITY_LABELS[value] ?? value);
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
    // Both events arrive carrying `reason` (the engine's own sentence for
    // the match) and the severity that was reached — and both used to drop
    // every bit of it on the floor, leaving a bare "Alert matched" while the
    // activity feed, from the same underlying event, managed "Alert:
    // First-ever aircraft" (review R2-15). *Which* alert is the meaningful
    // part of SPEC §52's "important alert transition".
    case "alert_matched": {
      const reason = stringDetail(detail, "reason");
      const severity = severityLabel(stringDetail(detail, "severity"));
      return { label: "Alert matched", detail: join([reason, severity]) };
    }
    case "alert_severity_upgraded": {
      const reason = stringDetail(detail, "reason");
      const from = severityLabel(stringDetail(detail, "from"));
      const to = severityLabel(stringDetail(detail, "to"));
      const ladder =
        from !== null && to !== null ? `${from} → ${to}` : (to ?? from);
      return {
        label: "Alert severity upgraded",
        detail: join([reason, ladder]),
      };
    }
    default:
      // Exhaustive by the vocabulary's Literal union; a future event type the
      // client hasn't learned yet still renders something rather than
      // crashing the timeline.
      return { label: type, detail: null };
  }
}
