/**
 * A small chip reporting the live socket's health.
 *
 * Deliberately quiet. A healthy stream is the normal case and does not deserve
 * an alarm, so `live` is a dim dot and a word; a stream that is down is the one
 * thing a watcher genuinely needs told, because an unchanging map otherwise
 * looks exactly like a sky with no traffic in it. That distinction — "nothing
 * is flying" versus "we have lost the feed" — is the whole reason the chip
 * exists, so it is never hidden entirely.
 */

import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { ConnectionStatus } from "@/lib/ws/liveSocket";
import { cn } from "@/lib/utils";

const LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
};

const DOT_CLASSES: Record<ConnectionStatus, string> = {
  connecting: "bg-muted-foreground",
  live: "bg-emerald-500",
  reconnecting: "bg-amber-500",
};

export function ConnectionStatusChip() {
  const status = useLiveAircraftStore((state) => state.connection);
  // Only read while live: a count next to "Connecting"/"Reconnecting" would
  // imply a picture the socket has not actually delivered yet.
  const aircraftCount = useLiveAircraftStore((state) =>
    status === "live" ? Object.keys(state.aircraft).length : 0,
  );

  return (
    <div
      role="status"
      aria-live="polite"
      data-status={status}
      className={cn(
        "pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-1.5",
        "rounded-full border border-border bg-card/90 px-2.5 py-1",
        "text-[11px] font-medium text-muted-foreground shadow-sm backdrop-blur-sm",
      )}
    >
      <span
        aria-hidden="true"
        className={cn("size-1.5 rounded-full", DOT_CLASSES[status])}
      />
      {LABELS[status]}
      {status === "live" && (
        // A quiet, user-visible confirmation that the live picture is
        // non-empty — not just that the socket connected. Also gives the
        // E2E live-map flow (roadmap slice 020) a stable, accessible signal
        // for "aircraft have actually arrived" beyond the connection state.
        <span data-testid="live-aircraft-count">
          · {aircraftCount} aircraft
        </span>
      )}
    </div>
  );
}
