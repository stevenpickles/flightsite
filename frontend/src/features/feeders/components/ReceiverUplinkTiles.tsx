import { StatTile } from "@/features/health/components/HealthCard";
import {
  formatBytesRate,
  formatCountOrNotObserved,
  formatPerMinute,
  formatRangeNm,
} from "@/features/feeders/lib/format";
import type { FeederReceiverUplink } from "@/lib/api/feeders";

interface ReceiverUplinkTilesProps {
  receiver: FeederReceiverUplink | null;
}

/**
 * The receiver's own `readsb` uplink summary (design record "Frontend"),
 * rendered as a row of tiles rather than a `FeederCard` of its own — it is
 * what the receiver is sending out, not a feed it receives status from.
 * Reuses `StatTile` from `features/health/components/HealthCard.tsx` so this
 * row reads as the same app as the Health page's own scorecard-style grid.
 */
export function ReceiverUplinkTiles({ receiver }: ReceiverUplinkTilesProps) {
  if (receiver === null) {
    return (
      <p className="text-sm text-muted-foreground">
        Receiver uplink not configured.
      </p>
    );
  }

  return (
    <div
      role="group"
      aria-label="Receiver uplink"
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
    >
      <StatTile
        label="Bytes out"
        value={formatBytesRate(receiver.bytes_out_rate_per_s)}
      />
      <StatTile
        label="Messages"
        value={formatPerMinute(receiver.messages_per_min)}
      />
      <StatTile
        label="Aircraft"
        value={formatCountOrNotObserved(receiver.aircraft)}
      />
      <StatTile
        label="MLAT inbound"
        value={formatCountOrNotObserved(receiver.mlat_inbound)}
      />
      <StatTile
        label="Samples dropped"
        value={formatCountOrNotObserved(receiver.samples_dropped)}
      />
      <StatTile
        label="Max range"
        value={formatRangeNm(receiver.max_range_nm)}
      />
    </div>
  );
}
