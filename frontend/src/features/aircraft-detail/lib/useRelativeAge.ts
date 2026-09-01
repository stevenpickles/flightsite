/**
 * Live-updating "last seen" age.
 *
 * `last_seen` (§3.3) is an absolute ISO instant, not a ticking counter, so
 * without this hook the panel would freeze at whatever age was true the
 * moment a frame last arrived. A one-second interval is enough resolution
 * for a human-readable age (`formatRelativeAge` only resolves to whole
 * seconds below a minute) without re-rendering faster than the eye can use.
 */

import { useEffect, useState } from "react";

import {
  formatRelativeAge,
  msSinceLastSeen,
} from "@/features/aircraft-detail/lib/format";

/** Returns a relative-age string for `lastSeenIso` that re-renders once a
 * second on its own, independent of whether new WebSocket frames arrive.
 * `null` input (no selection yet) renders `null`. */
export function useRelativeAge(lastSeenIso: string | null): string | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (lastSeenIso === null) {
      return;
    }
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(id);
  }, [lastSeenIso]);

  if (lastSeenIso === null) {
    return null;
  }
  return formatRelativeAge(msSinceLastSeen(lastSeenIso, now));
}
