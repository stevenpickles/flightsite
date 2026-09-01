/**
 * SPEC §61 scorecard row (roadmap slice 034): aircraft currently visible,
 * positions/sec, messages/sec, max range today/ever, unique aircraft
 * today/since T0, decoder and FlightSite uptime, and receiver health.
 *
 * Polls `GET /api/v1/receiver/scorecard` on a short interval
 * (`SCORECARD_POLL_MS`, `lib/api/receiverStats.ts`) rather than riding the
 * live WebSocket: the scorecard's own fields (decoder uptime, unique-today
 * counts, lifetime maxima) come from SQLite reads with no live-store
 * equivalent, so there is nothing for a WS frame to carry that would make
 * this cheaper than a periodic REST poll.
 */
import {
  AlertTriangle,
  CheckCircle2,
  FlaskConical,
  HelpCircle,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import type { UnitSystem } from "@/lib/api/config";
import {
  useReceiverScorecardQuery,
  type ReceiverHealth,
} from "@/lib/api/receiverStats";
import {
  formatCount,
  formatDistance,
  formatDurationCompact,
  formatRatePerSec,
} from "@/features/receiver/lib/format";

interface StatTileProps {
  label: string;
  value: ReactNode;
  secondary?: ReactNode;
}

function StatTile({ label, value, secondary }: StatTileProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-card-foreground">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {secondary !== undefined && (
        <p className="mt-0.5 text-xs text-muted-foreground">{secondary}</p>
      )}
    </div>
  );
}

const HEALTH_PRESENTATION: Record<
  ReceiverHealth,
  { label: string; icon: LucideIcon }
> = {
  ok: { label: "OK", icon: CheckCircle2 },
  no_stats: { label: "No decoder stats", icon: AlertTriangle },
  unknown: { label: "Unknown", icon: HelpCircle },
  demo: { label: "Demo mode", icon: FlaskConical },
};

function HealthTile({ health }: { health: ReceiverHealth }) {
  const { label, icon: Icon } = HEALTH_PRESENTATION[health];
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-card-foreground">
      <p className="text-xs text-muted-foreground">Health</p>
      {/* Icon + text label, never color alone (SPEC §80). */}
      <p className="mt-1 flex items-center gap-1.5 text-xl font-semibold">
        <Icon className="size-5" aria-hidden={true} />
        {label}
      </p>
    </div>
  );
}

export interface ReceiverScorecardProps {
  units: UnitSystem;
}

export function ReceiverScorecard({ units }: ReceiverScorecardProps) {
  const { data, isLoading, isError } = useReceiverScorecardQuery();

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading scorecard…</p>;
  }

  if (isError || data === undefined) {
    return (
      <p className="text-sm text-destructive">Could not load the scorecard.</p>
    );
  }

  return (
    <div
      role="group"
      aria-label="Receiver scorecard"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
    >
      <StatTile
        label="Aircraft visible"
        value={formatCount(data.current_visible)}
        secondary={`${formatCount(data.current_positioned)} positioned`}
      />
      <StatTile
        label="Messages/sec"
        value={formatRatePerSec(data.messages_per_sec, "msg")}
      />
      <StatTile
        label="Positions/sec"
        value={formatRatePerSec(data.positions_per_sec, "pos")}
      />
      <StatTile
        label="Max range today"
        value={formatDistance(data.max_range_today_nm, units) ?? "—"}
      />
      <StatTile
        label="Max range ever"
        value={formatDistance(data.max_range_ever_nm, units) ?? "—"}
      />
      <StatTile
        label="Unique aircraft today"
        value={formatCount(data.unique_aircraft_today)}
      />
      <StatTile
        label="Unique aircraft since T0"
        value={formatCount(data.unique_aircraft_since_t0)}
      />
      <StatTile
        label="Decoder uptime"
        value={formatDurationCompact(data.decoder_uptime_s)}
      />
      <StatTile
        label="FlightSite uptime"
        value={formatDurationCompact(data.flightsite_uptime_s)}
      />
      <HealthTile health={data.health} />
    </div>
  );
}
