import { DetailRow, HealthCard } from "@/features/health/components/HealthCard";
import { StatusPill } from "@/features/health/components/StatusPill";
import { enrichmentBudgetPresentation } from "@/features/health/lib/status";
import {
  formatCount,
  formatReceiverLocalDateTime,
} from "@/features/receiver/lib/format";
import type { DiagnosticsEnrichment } from "@/lib/api/diagnostics";

export interface EnrichmentHealthCardProps {
  enrichment: DiagnosticsEnrichment;
  /** The receiver's configured timezone, so the reset instant is shown in
   * the operator's local time even though the budget rolls over at midnight
   * UTC — the rollover is a UTC fact, but "when does that happen for me" is
   * the question this row exists to answer. */
  timezone: string;
}

/**
 * Route enrichment on the Health page (SPEC §28, §67; roadmap slice 070).
 *
 * Beyond the counters slice 042 already showed, this reports the two things
 * that decide whether a paid provider quota survives the month: how much of
 * today's lookup budget is left, and how much of the traffic the cache is
 * absorbing. Both come straight from `/api/v1/diagnostics`.
 *
 * Every new row is conditional on its block being present, so a frontend
 * newer than its backend degrades to exactly the card slice 042 shipped
 * instead of rendering rows of zeroes that would read as "the cache never
 * hits" rather than "this backend does not say".
 */
export function EnrichmentHealthCard({
  enrichment,
  timezone,
}: EnrichmentHealthCardProps) {
  const { budget, cache } = enrichment;
  const budgetStatus = enrichmentBudgetPresentation(budget);

  return (
    <HealthCard
      titleId="health-enrichment"
      title="Route enrichment"
      description="Route lookups: the offline route directory, plus AeroDataBox when configured (SPEC §28)."
      status={
        budgetStatus !== null ? (
          <StatusPill tone={budgetStatus.tone} label={budgetStatus.label} />
        ) : undefined
      }
    >
      <DetailRow label="Enabled" value={enrichment.enabled ? "Yes" : "No"} />
      {enrichment.provider !== undefined && (
        <DetailRow
          label="Provider"
          value={
            enrichment.provider === "aerodatabox"
              ? "AeroDataBox"
              : "Directory only"
          }
        />
      )}
      <DetailRow label="Lookups" value={formatCount(enrichment.lookups)} />
      <DetailRow label="Failures" value={formatCount(enrichment.failures)} />
      <DetailRow
        label="Circuit breaker"
        value={enrichment.circuit_open ? "Open" : "Closed"}
      />
      {budget !== undefined && (
        <>
          <DetailRow
            label="Daily budget"
            value={
              budget.limit === null
                ? `${formatCount(budget.used_today)} used · uncapped`
                : `${formatCount(budget.used_today)} / ${formatCount(budget.limit)} used`
            }
          />
          {budget.limit !== null && (
            <DetailRow
              label="Remaining today"
              value={formatCount(budget.remaining ?? 0)}
            />
          )}
          <DetailRow
            label="Budget resets"
            value={formatReceiverLocalDateTime(budget.resets_at, timezone)}
          />
        </>
      )}
      {cache !== undefined && (
        <>
          <DetailRow label="Cache hits" value={formatCount(cache.hits)} />
          <DetailRow label="Cache misses" value={formatCount(cache.misses)} />
          <DetailRow
            label="Routes learned"
            value={formatCount(cache.learned)}
          />
          {cache.directory_hits !== undefined && (
            <DetailRow
              label="Directory hits"
              value={formatCount(cache.directory_hits)}
            />
          )}
          {cache.stale_served !== undefined && (
            <DetailRow
              label="Last-known routes served"
              value={formatCount(cache.stale_served)}
            />
          )}
        </>
      )}
    </HealthCard>
  );
}
