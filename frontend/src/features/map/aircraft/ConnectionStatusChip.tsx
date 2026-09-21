/**
 * A small chip reporting the live socket's health.
 *
 * Deliberately quiet. A healthy stream is the normal case and does not deserve
 * an alarm, so `live` is a dim dot and a word; a stream that is down is the one
 * thing a watcher genuinely needs told, because an unchanging map otherwise
 * looks exactly like a sky with no traffic in it. That distinction — "nothing
 * is flying" versus "we have lost the feed" — is the whole reason the chip
 * exists, so it is never hidden entirely.
 *
 * Four things it can say, in escalating order (issues R1-03, R1-04):
 *
 * 1. **Connecting** — the first attempt, and only briefly.
 * 2. **Reconnecting** — a stream that was working has dropped. The attempt
 *    number rides along so a watcher can see retries happening rather than
 *    guess.
 * 3. **Live feed unavailable — retrying** — past {@link ESCALATE_AFTER_ATTEMPTS}
 *    failures, whichever of the two states we are in. This is the wording the
 *    review found missing: a socket whose upgrade a reverse proxy does not
 *    forward never leaves `connecting`, so the chip said "Connecting" for as
 *    long as the tab was open, over a map with no aircraft on it, and the two
 *    most important cases in the product were indistinguishable.
 * 4. **· last update 12s ago** — appended whenever the picture on screen is
 *    no longer being fed by anything, socket or REST fallback. A kept picture
 *    is only honest if its age is on screen beside it.
 *
 * What is announced, and what is only shown. The attempt number and the age
 * both change on a timer, and a `role="status"` region that re-reads itself
 * every second buries the one announcement that matters. Both are therefore
 * `aria-hidden`: a screen reader hears "Reconnecting" once and "Live feed
 * unavailable — retrying" once, at the moment each becomes true, which is
 * exactly the set of state changes worth interrupting for.
 */

import { useEffect, useState } from "react";

import { formatRelativeAge } from "@/features/aircraft-detail/lib/format";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { ConnectionStatus } from "@/lib/ws/liveSocket";
import { cn } from "@/lib/utils";

const LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
};

/** What the chip says once retrying has stopped being a formality. */
const UNAVAILABLE_LABEL = "Live feed unavailable — retrying";

/**
 * Consecutive failed attempts before the chip stops being reassuring.
 *
 * Three, which `lib/ws/backoff.ts`'s 500 ms base puts at roughly 3-4 s in:
 * long enough that an ordinary backend restart or a laptop waking up has
 * already succeeded and nothing alarming has been said, short enough that a
 * blocked upgrade is named as a problem while the user is still looking at
 * the page rather than after they have concluded the sky is empty.
 */
export const ESCALATE_AFTER_ATTEMPTS = 3;

const DOT_CLASSES: Record<ConnectionStatus, string> = {
  connecting: "bg-muted-foreground",
  live: "bg-emerald-500",
  reconnecting: "bg-amber-500",
};

/** How often the "last update" age is recomputed while it is on screen.
 * One second, the resolution `formatRelativeAge` reports below a minute;
 * the interval runs only while the picture is stale, so a healthy map
 * schedules nothing. */
const AGE_TICK_MS = 1_000;

export function ConnectionStatusChip() {
  const status = useLiveAircraftStore((state) => state.connection);
  const attempt = useLiveAircraftStore((state) => state.connectionAttempt);
  const stale = useLiveAircraftStore((state) => state.stale);
  const lastUpdate = useLiveAircraftStore((state) => state.lastUpdate);
  // Only read while live: a count next to "Connecting"/"Reconnecting" would
  // imply a picture the socket has not actually delivered yet.
  const aircraftCount = useLiveAircraftStore((state) =>
    status === "live" ? Object.keys(state.aircraft).length : 0,
  );

  const showAge = stale && lastUpdate !== null;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!showAge) {
      return undefined;
    }
    const tick = () => {
      setNow(Date.now());
    };
    // The zero-delay timer, rather than a direct call, is what keeps the
    // first reading current without a setState in the effect body: `now` is
    // otherwise whatever it was when the chip mounted, which for a tab that
    // has been open a while would render one frame of nonsense before the
    // first interval tick corrected it.
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, AGE_TICK_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [showAge]);

  const escalated = status !== "live" && attempt >= ESCALATE_AFTER_ATTEMPTS;
  const label = escalated ? UNAVAILABLE_LABEL : LABELS[status];

  return (
    <div
      role="status"
      aria-live="polite"
      data-status={status}
      data-stale={stale ? "true" : "false"}
      data-escalated={escalated ? "true" : "false"}
      className={cn(
        "pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-1.5",
        "rounded-full border border-border bg-card/90 px-2.5 py-1",
        "text-[11px] font-medium text-muted-foreground shadow-sm backdrop-blur-sm",
        escalated && "text-amber-600 dark:text-amber-400",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          escalated ? "bg-amber-500" : DOT_CLASSES[status],
        )}
      />
      {label}
      {status !== "live" && attempt > 0 && (
        <span aria-hidden="true" data-testid="connection-attempt">
          (attempt {attempt})
        </span>
      )}
      {status === "live" && (
        // A quiet, user-visible confirmation that the live picture is
        // non-empty — not just that the socket connected. Also gives the
        // E2E live-map flow (roadmap slice 020) a stable, accessible signal
        // for "aircraft have actually arrived" beyond the connection state.
        <span data-testid="live-aircraft-count">
          · {aircraftCount} aircraft
        </span>
      )}
      {showAge && (
        <span aria-hidden="true" data-testid="connection-last-update">
          · last update {formatRelativeAge(Math.max(0, now - lastUpdate))}
        </span>
      )}
    </div>
  );
}
