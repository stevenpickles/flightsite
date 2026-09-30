import { Link } from "react-router-dom";

import { DetailRow, HealthCard } from "@/features/health/components/HealthCard";
import { StatusPill } from "@/features/health/components/StatusPill";
import { formatReceiverLocalDateTime } from "@/features/receiver/lib/format";
import type {
  DiagnosticsActiveSelfAlert,
  DiagnosticsSelfAlerts,
  SelfAlertCondition,
} from "@/lib/api/diagnostics";

interface SelfAlertsHealthCardProps {
  selfAlerts: DiagnosticsSelfAlerts;
  timezone: string;
}

const CONDITION_LABEL: Record<SelfAlertCondition, string> = {
  decoder_down: "Decoder down",
  message_rate: "Message rate collapsed",
  feeder_offline: "Feed offline",
};

/** "Feed offline: FlightRadar24" — a feeder row names which feeder. */
function alertLabel(alert: DiagnosticsActiveSelfAlert): string {
  const base = CONDITION_LABEL[alert.condition] ?? alert.condition;
  const subject = alert.label ?? alert.subject;
  return subject === null ? base : `${base}: ${subject}`;
}

/**
 * What the message-rate condition cannot judge yet, in words — or `null`
 * when it can. Stated on the card because a condition that silently never
 * fires for its first fortnight would read as a broken one.
 */
function rateNote(selfAlerts: DiagnosticsSelfAlerts): string | null {
  const rate = selfAlerts.conditions.message_rate;
  if (rate === undefined) {
    return null;
  }
  if (rate.state === "learning") {
    const weeks = rate.baseline_weeks ?? 0;
    return `Learning this hour's baseline (${weeks} of 2 weeks recorded)`;
  }
  if (rate.state === "quiet") {
    return "This hour is too quiet to judge";
  }
  return null;
}

/**
 * Roadmap slice 088's "Active self-alerts" card: every receiver self-alert
 * condition currently raised, each with the moment it *began* in the
 * receiver's timezone. Read from `diagnostics.self_alerts`
 * (`docs/API.md` §3.10) and rendered only when that block is present —
 * absent from any backend older than the slice, the same convention
 * `FeedersHealthCard` follows.
 *
 * The status pill counts what is active; a card whose three conditions are
 * all switched off says so (`Off`) rather than claiming health it is not
 * checking.
 */
export function SelfAlertsHealthCard({
  selfAlerts,
  timezone,
}: SelfAlertsHealthCardProps) {
  const active = selfAlerts.active;
  const conditions = Object.values(selfAlerts.conditions);
  const allOff =
    conditions.length > 0 && conditions.every((c) => c?.enabled === false);
  const status =
    active.length > 0
      ? { tone: "bad" as const, label: `${active.length} active` }
      : allOff
        ? { tone: "idle" as const, label: "Off" }
        : { tone: "ok" as const, label: "None active" };
  const note = rateNote(selfAlerts);

  return (
    <HealthCard
      titleId="health-self-alerts"
      title="Active self-alerts"
      description="The station warning about itself: decoder, message rate, feeders."
      status={<StatusPill tone={status.tone} label={status.label} />}
    >
      {active.length === 0 ? (
        <p className="py-1 text-sm text-muted-foreground">
          {allOff
            ? "Every self-alert is switched off."
            : "Nothing is wrong with the station right now."}
        </p>
      ) : (
        <ul aria-label="Active self-alerts">
          {active.map((alert) => (
            <li key={`${alert.condition}:${alert.subject ?? ""}`}>
              <DetailRow
                label={alertLabel(alert)}
                value={
                  alert.since === null
                    ? "—"
                    : `since ${formatReceiverLocalDateTime(alert.since, timezone)}`
                }
              />
            </li>
          ))}
        </ul>
      )}
      {note !== null && (
        <p className="mt-2 text-xs text-muted-foreground">{note}</p>
      )}
      <Link
        to="/settings#settings-self-alerts"
        className="mt-3 inline-block text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        Self-alert settings
      </Link>
    </HealthCard>
  );
}
