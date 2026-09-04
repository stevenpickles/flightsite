import { Link } from "react-router-dom";

import {
  DetailRow,
  HealthCard,
  StatTile,
} from "@/features/health/components/HealthCard";
import { EnrichmentHealthCard } from "@/features/health/components/EnrichmentHealthCard";
import { NotificationHealthCard } from "@/features/health/components/NotificationHealthCard";
import { RecentErrorsSection } from "@/features/health/components/RecentErrorsSection";
import { StatusPill } from "@/features/health/components/StatusPill";
import {
  formatAgeAgo,
  formatBytes,
  formatPercent,
  humanizeKey,
  NOT_AVAILABLE,
} from "@/features/health/lib/format";
import {
  decoderPresentation,
  integrityPresentation,
  maintenancePresentation,
  metadataSourcePresentation,
  overallPresentation,
  recoveryPresentation,
  vacuumRefusalPresentation,
} from "@/features/health/lib/status";
import {
  formatCount,
  formatDurationCompact,
  formatReceiverLocalDateTime,
} from "@/features/receiver/lib/format";
import { useConfigQuery } from "@/lib/api/config";
import { useDiagnosticsQuery } from "@/lib/api/diagnostics";

/**
 * The health and diagnostics area — SPEC §67, roadmap slice 042.
 *
 * The whole point, in the spec's own words, is that *"the user should not
 * have to SSH into the Pi to determine whether FlightSite is healthy"*. So
 * every item §67 lists has a home here, and each one renders a degraded or
 * unknown state as deliberately as it renders a healthy one: a first-run
 * install with no receiver, no metadata and no integrity check yet is a
 * normal state to be shown clearly, not an error to apologise for.
 *
 * Reached from the Receiver and Settings pages rather than the sidebar: SPEC
 * §10 fixes that at seven sections, so this follows the `/activity`
 * precedent of a route inside the shell with no `NAV_ITEMS` entry.
 */
export function HealthPage() {
  const { data, isLoading, isError, error } = useDiagnosticsQuery();
  const { data: config } = useConfigQuery();
  const timezone = config?.config.timezone ?? "UTC";

  if (isLoading) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-semibold">Health</h1>
        <p className="mt-4 text-sm text-muted-foreground">
          Loading diagnostics…
        </p>
      </div>
    );
  }

  if (isError || data === undefined) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-semibold">Health</h1>
        {/* The one failure the page cannot report from the payload: if
            diagnostics itself is unreachable, the backend is the problem. */}
        <p className="mt-4 text-sm text-destructive">
          Could not load diagnostics
          {error instanceof Error ? `: ${error.message}` : "."}{" "}
          FlightSite&apos;s backend may be down — check the container logs.
        </p>
      </div>
    );
  }

  const overall = overallPresentation(data.status);
  const decoder = decoderPresentation(data.decoder.state);
  const integrity = integrityPresentation(data.database.quick_check.healthy);
  const maintenance = maintenancePresentation(
    data.database.maintenance.healthy,
    data.database.maintenance.cycles,
  );
  const recovery = recoveryPresentation(data.database.recovery.anomalies);
  const vacuumRefusal =
    data.database.maintenance.vacuum_refusal === null
      ? null
      : vacuumRefusalPresentation(
          data.database.maintenance.vacuum_refusal.reason,
        );

  return (
    <div className="flex flex-col gap-6 p-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Health</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Everything you would otherwise SSH in to check.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill
            tone={overall.tone}
            label={overall.label}
            className="px-3 py-1 text-sm"
          />
          <Link
            to="/receiver"
            className="text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            Receiver
          </Link>
        </div>
      </header>

      {/* SPEC §67's headline figures, in one scan. */}
      <div
        role="group"
        aria-label="Health summary"
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
      >
        <StatTile
          label="Decoder"
          value={
            <span className="flex items-center gap-2 text-base">
              <StatusPill tone={decoder.tone} label={decoder.label} />
            </span>
          }
          secondary={
            data.decoder.last_error !== null
              ? data.decoder.last_error
              : `${formatCount(data.decoder.updates_ingested)} updates ingested`
          }
        />
        <StatTile
          label="Last aircraft update"
          value={formatAgeAgo(data.live.last_aircraft_update_age_s)}
          secondary={`${data.live.total} visible now`}
        />
        <StatTile
          label="Backend uptime"
          value={formatDurationCompact(data.uptime.backend_s)}
          secondary={
            data.uptime.decoder_s !== null
              ? `Decoder up ${formatDurationCompact(data.uptime.decoder_s)}`
              : undefined
          }
        />
        <StatTile
          label="Version"
          value={data.versions.backend}
          secondary={
            data.versions.schema_revision !== null
              ? `Schema ${data.versions.schema_revision}`
              : undefined
          }
        />
        <StatTile
          label="Database size"
          value={formatBytes(data.database.storage.database_bytes)}
          secondary={`WAL ${formatBytes(data.database.storage.wal_bytes)}`}
        />
        <StatTile
          label="Free disk space"
          value={formatBytes(data.database.storage.disk_free_bytes)}
          secondary={
            data.database.storage.reclaimable_ratio !== null
              ? `${formatPercent(data.database.storage.reclaimable_ratio)} reclaimable`
              : undefined
          }
        />
        <StatTile
          label="Metadata age"
          value={
            data.metadata.age_s !== null
              ? formatDurationCompact(data.metadata.age_s)
              : NOT_AVAILABLE
          }
          secondary={
            data.metadata.age_s === null
              ? "Never imported"
              : "since last import"
          }
        />
        <StatTile
          label="WebSocket clients"
          value={data.websocket.clients}
          secondary={`${data.websocket.disconnects} dropped since start-up`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <HealthCard
          titleId="health-decoder"
          title="Decoder"
          description="SPEC §67 connection state and last successful update."
          status={<StatusPill tone={decoder.tone} label={decoder.label} />}
        >
          <DetailRow
            label="Configured"
            value={data.decoder.configured ? "Yes" : "No"}
          />
          <DetailRow
            label="Demo mode"
            value={data.decoder.demo_mode ? "On" : "Off"}
          />
          <DetailRow
            label="Last success"
            value={
              data.decoder.last_success !== null
                ? formatReceiverLocalDateTime(
                    data.decoder.last_success,
                    timezone,
                  )
                : NOT_AVAILABLE
            }
          />
          <DetailRow
            label="Consecutive failures"
            value={data.decoder.consecutive_failures}
          />
          <DetailRow
            label="Batches ingested"
            value={formatCount(data.decoder.batches_ingested)}
          />
          {data.decoder.last_error !== null && (
            <p className="mt-2 text-xs break-all text-destructive">
              {data.decoder.last_error}
            </p>
          )}
        </HealthCard>

        <HealthCard
          titleId="health-database"
          title="Database"
          description="Integrity, size and maintenance (SPEC §67, §70)."
          status={<StatusPill tone={integrity.tone} label={integrity.label} />}
        >
          <DetailRow
            label="Integrity check"
            value={
              data.database.quick_check.checked_at !== null
                ? formatReceiverLocalDateTime(
                    data.database.quick_check.checked_at,
                    timezone,
                  )
                : "Not yet run"
            }
          />
          <DetailRow
            label="Maintenance"
            value={
              <StatusPill
                tone={maintenance.tone}
                label={maintenance.label}
                className="font-normal"
              />
            }
          />
          <DetailRow
            label="Maintenance cycles"
            value={formatCount(data.database.maintenance.cycles)}
          />
          <DetailRow
            label="Shutdown recovery"
            value={
              <StatusPill
                tone={recovery.tone}
                label={recovery.label}
                className="font-normal"
              />
            }
          />
          <DetailRow
            label="Reclaimable"
            value={formatBytes(data.database.storage.reclaimable_bytes)}
          />
          {vacuumRefusal !== null && (
            <DetailRow
              label="Compaction"
              value={
                <span className="flex flex-col items-end gap-1">
                  <StatusPill
                    tone={vacuumRefusal.tone}
                    label={vacuumRefusal.label}
                    className="font-normal"
                  />
                  {data.database.maintenance.vacuum_refusal?.reason ===
                    "insufficient_free_space" && (
                    <span className="text-xs text-muted-foreground">
                      {`Needs ${formatBytes(
                        data.database.maintenance.vacuum_refusal
                          .required_free_bytes,
                      )} free, has ${formatBytes(
                        data.database.maintenance.vacuum_refusal
                          .available_free_bytes,
                      )}`}
                    </span>
                  )}
                </span>
              }
            />
          )}
          {data.database.quick_check.rows.length > 0 && (
            <ul className="mt-2 list-disc pl-4 text-xs text-destructive">
              {data.database.quick_check.rows.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          )}
        </HealthCard>

        <HealthCard
          titleId="health-rows"
          title="Stored data"
          description="SPEC §67's useful row counts."
        >
          {Object.entries(data.database.row_counts).map(([table, count]) => (
            <DetailRow
              key={table}
              label={humanizeKey(table)}
              value={formatCount(count)}
            />
          ))}
        </HealthCard>

        <HealthCard
          titleId="health-metadata"
          title="Metadata datasets"
          description="How old the aircraft and airport data is (SPEC §67)."
        >
          {data.metadata.sources.map((source) => {
            const presentation = metadataSourcePresentation(
              source.status,
              source.running,
            );
            return (
              <div
                key={source.source}
                className="border-b border-border py-2 last:border-0"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{source.source}</span>
                  <StatusPill
                    tone={presentation.tone}
                    label={presentation.label}
                  />
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {source.last_success_at !== null
                    ? `Imported ${formatAgeAgo(source.age_s)} · ${formatCount(source.row_count)} rows`
                    : "No successful import yet"}
                </p>
                {source.last_error !== null && (
                  <p className="mt-0.5 text-xs break-all text-destructive">
                    {source.last_error}
                  </p>
                )}
              </div>
            );
          })}
          <Link
            to="/settings"
            className="mt-3 inline-block text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            Update metadata in Settings
          </Link>
        </HealthCard>

        <NotificationHealthCard notifications={data.notifications} />

        <EnrichmentHealthCard
          enrichment={data.enrichment}
          timezone={timezone}
        />
      </div>

      <section
        aria-labelledby="health-errors-heading"
        className="flex flex-col gap-3"
      >
        <h2 id="health-errors-heading" className="text-lg font-semibold">
          Recent errors
        </h2>
        <RecentErrorsSection
          recentErrors={data.recent_errors}
          counters={data.counters}
          timezone={timezone}
        />
      </section>

      <p className="text-xs text-muted-foreground">
        Generated {formatReceiverLocalDateTime(data.generated_at, timezone)} ·
        refreshes automatically.
      </p>
    </div>
  );
}
