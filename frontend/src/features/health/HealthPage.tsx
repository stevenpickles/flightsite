import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
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
  liveEventConsumerPresentation,
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
// R4-14: shared with Settings' Aircraft Metadata section, so the same
// source reads as the same name ("FAA", not "faa") on both pages.
import { rowNoun, sourceLabel } from "@/lib/metadata/sources";

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

/** The current time, re-read every `intervalMs` — the same lazy-initial-state
 * plus `setInterval` shape `useRelativeAge` uses, which keeps every
 * `Date.now()` read out of the render body itself (`react-hooks/purity`):
 * the only call at render time is the `useState` lazy initializer, which
 * only ever runs once, and the periodic call lives in a timer callback. Used
 * for the R4-04 "generated N ago" readouts, which would otherwise freeze at
 * whatever age was true on the render that received the payload. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function HealthPage() {
  const { data, isLoading, isError, error, refetch, isRefetching } =
    useDiagnosticsQuery();
  const { data: config } = useConfigQuery();
  const timezone = config?.config.timezone ?? "UTC";
  // Called unconditionally, before either early return, so the age readouts
  // below stay live without breaking the Rules of Hooks.
  const now = useNow(15_000);

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

  // R4-04: this page exists to be readable *while* things are going wrong,
  // so a full-page error is reserved for "never loaded" — the one state
  // with nothing else to show. A poll that starts failing after a good
  // load keeps rendering the last payload (`data` stays populated; React
  // Query does not clear it on a background refetch error) with a warning
  // banner below, rather than replacing every card with a red line.
  if (data === undefined) {
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

  const generatedAgeS = Math.max(
    0,
    (now - new Date(data.generated_at).getTime()) / 1000,
  );

  const overall = overallPresentation(data.status);
  const decoder = decoderPresentation(data.decoder.state);
  const integrity = integrityPresentation(data.database.quick_check.healthy);
  const maintenance = maintenancePresentation(
    data.database.maintenance.healthy,
    data.database.maintenance.cycles,
  );
  const recovery = recoveryPresentation(data.database.recovery.anomalies);
  // Undefined on a backend older than slice 075, which published no
  // per-consumer breakdown at all — the card is dropped rather than filled
  // with zeroes that would read as "nothing has ever been shed".
  const liveEvents = data.live_events;
  const resyncing =
    liveEvents?.subscribers.some((subscriber) => subscriber.overflowed) ??
    false;
  // R4-17: six near-identical zero rows are noise on a healthy install —
  // the per-consumer breakdown collapses behind a disclosure while every
  // consumer reads 0, and opens by itself (and stays open) the moment one
  // has something to say.
  const anyConsumerShedding =
    liveEvents?.subscribers.some((subscriber) => subscriber.dropped > 0) ??
    false;
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

      {isError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/50 bg-warning/10 p-3 text-sm"
        >
          <p className="text-warning">
            Refreshing failed — showing the state from{" "}
            {formatAgeAgo(generatedAgeS)}.
            {error instanceof Error ? ` (${error.message})` : ""}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isRefetching}
            onClick={() => {
              void refetch();
            }}
          >
            {isRefetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

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
          // R4-17: "disconnects", never "shed" — the Live events card below
          // uses "shed" for a different thing (events dropped from a
          // consumer's queue), and reusing the word here is exactly the
          // ambiguity issue #185 already burned this tile once for (until
          // slice 075 this secondary showed the live-event drop total under
          // the same word, which read as the browser feed having lost
          // clients when the persistence queue had).
          secondary={`${formatCount(data.websocket.disconnects)} client disconnects since start-up`}
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
                  <span className="text-sm font-medium">
                    {sourceLabel(source.source)}
                  </span>
                  <StatusPill
                    tone={presentation.tone}
                    label={presentation.label}
                  />
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {source.last_success_at !== null
                    ? `Imported ${formatAgeAgo(source.age_s)} · ${formatCount(source.row_count)} ${rowNoun(source.source)}`
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
            to="/settings#settings-metadata"
            className="mt-3 inline-block text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            Update metadata in Settings
          </Link>
        </HealthCard>

        {liveEvents !== undefined && (
          <HealthCard
            titleId="health-live-events"
            title="Live events"
            description="Shed live events by consumer; a consumer that fell behind resyncs from a snapshot."
            status={
              <StatusPill
                tone={resyncing ? "warn" : "ok"}
                label={resyncing ? "Resyncing" : "Keeping up"}
              />
            }
          >
            <DetailRow
              label="Events published"
              value={formatCount(liveEvents.published)}
            />
            <DetailRow
              label="Shed in total"
              value={formatCount(liveEvents.dropped)}
            />
            {/* R4-17: six near-identical rows are noise on a healthy
                install, so they collapse behind a disclosure unless one has
                something to say — open by itself the moment it does. Each
                row names the consumer the way the rest of the app does
                ("Live map feed", not "websocket") and adds the one-line
                consequence only while it is actually shedding. */}
            <details
              open={anyConsumerShedding}
              className="group mt-1 border-t border-border pt-1"
            >
              <summary className="cursor-pointer list-none text-xs text-muted-foreground [&::-webkit-details-marker]:hidden">
                <span className="group-open:hidden">
                  Show every consumer ({liveEvents.subscribers.length})
                </span>
                <span className="hidden group-open:inline">
                  Hide the per-consumer breakdown
                </span>
              </summary>
              <div className="mt-1 flex flex-col">
                {liveEvents.subscribers.map((subscriber) => {
                  const presentation = liveEventConsumerPresentation(
                    subscriber.name,
                  );
                  return (
                    <DetailRow
                      key={subscriber.name}
                      label={presentation.label}
                      value={
                        <span className="flex flex-col items-end gap-1">
                          <span>{`${formatCount(subscriber.dropped)} shed`}</span>
                          <span className="text-xs font-normal text-muted-foreground">
                            {`${formatCount(subscriber.pending)} / ${formatCount(
                              subscriber.capacity,
                            )} queued`}
                          </span>
                          {subscriber.dropped > 0 && (
                            <span className="text-xs font-normal text-muted-foreground">
                              {presentation.consequence}
                            </span>
                          )}
                          {subscriber.overflowed && (
                            <StatusPill
                              tone="warn"
                              label="Resyncing"
                              className="font-normal"
                            />
                          )}
                        </span>
                      }
                    />
                  );
                })}
              </div>
            </details>
          </HealthCard>
        )}

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
        {/* R4-04: states the age rather than a blanket "refreshes
            automatically" — the banner above already says so when that claim
            has stopped being true. */}
        Generated {formatReceiverLocalDateTime(data.generated_at, timezone)} (
        {formatAgeAgo(generatedAgeS)}).
      </p>
    </div>
  );
}
