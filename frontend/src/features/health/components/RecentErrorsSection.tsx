import { DetailRow, HealthCard } from "@/features/health/components/HealthCard";
import { StatusPill } from "@/features/health/components/StatusPill";
import { errorCountPresentation } from "@/features/health/lib/status";
import { formatReceiverLocalTime } from "@/features/receiver/lib/format";
import type { DiagnosticsErrorEntry } from "@/lib/api/diagnostics";

/** SPEC §67 names four error kinds; `other` catches anything outside a named
 * subsystem so a novel failure is still visible. */
const CATEGORY_LABELS: Record<string, string> = {
  ingestion: "Ingestion",
  database: "Database",
  enrichment: "Enrichment",
  websocket: "WebSocket",
  other: "Other",
};

const CATEGORY_ORDER = [
  "ingestion",
  "database",
  "enrichment",
  "websocket",
  "other",
] as const;

interface RecentErrorsSectionProps {
  recentErrors: Record<string, DiagnosticsErrorEntry[]>;
  counters: Record<string, number>;
  timezone: string;
}

function ErrorList({
  entries,
  timezone,
}: {
  entries: DiagnosticsErrorEntry[];
  timezone: string;
}) {
  if (entries.length === 0) {
    return (
      <p className="py-2 text-sm text-muted-foreground">
        No errors recorded since start-up.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border">
      {entries.map((entry, index) => (
        <li
          key={`${entry.at}-${entry.event}-${index}`}
          className="py-2 text-sm"
          data-testid="health-error-entry"
        >
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-medium break-all">{entry.event}</span>
            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
              {formatReceiverLocalTime(entry.at, timezone)}
            </span>
          </div>
          {entry.detail !== null && (
            <p className="mt-0.5 text-xs break-all text-muted-foreground">
              {entry.detail}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * SPEC §67's recent ingestion / database / enrichment / WebSocket errors.
 *
 * The counters beside each list are the totals since start-up; the list is
 * the bounded tail. Both are shown because they answer different questions —
 * "has this ever gone wrong" and "is it going wrong now".
 */
export function RecentErrorsSection({
  recentErrors,
  counters,
  timezone,
}: RecentErrorsSectionProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {CATEGORY_ORDER.map((category) => {
        const entries = recentErrors[category] ?? [];
        const presentation = errorCountPresentation(entries.length);
        return (
          <HealthCard
            key={category}
            titleId={`health-errors-${category}`}
            title={`${CATEGORY_LABELS[category]} errors`}
            status={
              <StatusPill tone={presentation.tone} label={presentation.label} />
            }
          >
            <ErrorList entries={entries} timezone={timezone} />
          </HealthCard>
        );
      })}
      <HealthCard
        titleId="health-counters"
        title="Counters since start-up"
        description="SPEC §68's internal counters."
      >
        {Object.entries(counters).map(([name, value]) => (
          <DetailRow
            key={name}
            label={name.replace(/_/g, " ")}
            value={value.toLocaleString()}
          />
        ))}
      </HealthCard>
    </div>
  );
}
