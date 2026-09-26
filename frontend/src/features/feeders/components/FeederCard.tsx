import { ExternalLink } from "lucide-react";

import { DetailRow, HealthCard } from "@/features/health/components/HealthCard";
import { StatusPill } from "@/features/health/components/StatusPill";
import {
  formatAdsbOutChip,
  formatMlatChip,
  formatRelativeAndAbsolute,
} from "@/features/feeders/lib/format";
import {
  feederStatePresentation,
  observabilityNote,
} from "@/features/feeders/lib/status";
import type { FeederEntry } from "@/lib/api/feeders";

interface FeederCardProps {
  feeder: FeederEntry;
  timezone: string;
  nowMs: number;
}

/**
 * One feeder's status (design record "Frontend"): a `StatusPill` whose tone
 * follows the state machine (up=ok, degraded=warn, down=bad, unknown=unknown
 * — never color alone, SPEC §80), since/last-data-sent as relative-plus-
 * absolute receiver-local time, the MLAT and ADS-B-out chips when this
 * feeder carries either signal, the backend's own `message`, an
 * observability note when the Docker socket would be needed for more, and
 * the "Open"/"View stats" links.
 *
 * Reuses `HealthCard`/`DetailRow`/`StatusPill` from the health area rather
 * than a parallel card component — the same "same app" reasoning
 * `ReceiverUplinkTiles` follows for `StatTile`.
 */
export function FeederCard({ feeder, timezone, nowMs }: FeederCardProps) {
  const presentation = feederStatePresentation(feeder.state);
  const mlatChip = formatMlatChip(feeder.mlat);
  const adsbOutChip = formatAdsbOutChip(feeder.adsb_out);
  const note = observabilityNote(feeder.observability);

  return (
    // `data-testid`/`data-feeder` rather than relying on `HealthCard`'s own
    // (label-derived) markup alone: `e2e/tests/12-feeders.spec.ts` needs a
    // stable, per-feeder hook that survives a label rename — the same
    // `data-testid="feeder-card"` + `data-feeder="<name>"` shape
    // `10-metadata-update`'s per-source cards use.
    <div data-testid="feeder-card" data-feeder={feeder.name}>
      <HealthCard
        titleId={`feeder-${feeder.name}`}
        title={feeder.label}
        description={feeder.kind}
        status={
          <StatusPill tone={presentation.tone} label={presentation.label} />
        }
      >
        <DetailRow
          label="Since"
          value={formatRelativeAndAbsolute(feeder.since, timezone, nowMs)}
        />
        <DetailRow
          label="Last data sent"
          value={formatRelativeAndAbsolute(
            feeder.last_data_sent_at,
            timezone,
            nowMs,
          )}
        />

        {(mlatChip !== null || adsbOutChip !== null) && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {mlatChip !== null && (
              <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                {mlatChip}
              </span>
            )}
            {adsbOutChip !== null && (
              <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                {adsbOutChip}
              </span>
            )}
          </div>
        )}

        {feeder.message !== null && (
          <p className="mt-2 text-xs break-all text-muted-foreground">
            {feeder.message}
          </p>
        )}

        {note !== null && <p className="mt-2 text-xs text-warning">{note}</p>}

        <div className="mt-3 flex flex-wrap gap-3">
          {feeder.web_url !== null && (
            <a
              href={feeder.web_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
            >
              {`Open ${feeder.label}`}
              <ExternalLink className="size-3" aria-hidden="true" />
            </a>
          )}
          {/* Never fetched — this is a plain navigation to a 302 redirect the
              backend serves, per the design record's redaction rule that the
              secret stats URL it points at must never reach `/api/v1`, logs
              or the DOM. Rendered only when `stats_link` is true. */}
          {feeder.stats_link && (
            <a
              href={`/api/internal/feeders/${encodeURIComponent(feeder.name)}/stats-link`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
            >
              {`View stats on ${feeder.label}`}
              <ExternalLink className="size-3" aria-hidden="true" />
            </a>
          )}
        </div>
      </HealthCard>
    </div>
  );
}
