/**
 * The receiver-local "today" date, computed client-side so the Today panel
 * (roadmap slice 036) knows when to refetch across a local-midnight rollover.
 *
 * The backend resolves `preset=today` against the *receiver's* IANA zone,
 * never the browser's (`docs/API.md` §3.7) — a card behind a browser in
 * another timezone must not decide on its own that a new day has started, or
 * ask for a fresh window when the receiver's day has not actually turned
 * over. So the same computation happens here, against the same zone
 * (`useReceiverQuery().data.timezone`), purely to know *when* to ask the
 * server again — the server's response, not this module, is still the
 * source of truth for what "today" contains.
 */
import { useEffect, useState } from "react";

/** How often the local date is re-checked. Coarse on purpose — a card that
 * is fresh within half a minute of receiver-local midnight is plenty, and
 * `useAnalyticsSummaryQuery`'s 60 s `staleTime` and focus refetch are what
 * keep the figures themselves current the rest of the time. */
const POLL_INTERVAL_MS = 30_000;

/** The receiver-local calendar date (`YYYY-MM-DD`) for `at`, in `timezone`.
 *
 * `Intl.DateTimeFormat`'s `en-CA` locale is picked only because it happens to
 * format as ISO `YYYY-MM-DD` — the locale itself carries no other meaning
 * here, the same trick `features/analytics/lib/format.ts` avoids needing by
 * working from already-formatted day strings instead of computing one.
 */
export function receiverLocalDate(
  timezone: string,
  at: Date = new Date(),
): string {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(at);
  } catch {
    // An unrecognized zone (a receiver mid-setup, or a stale cached value)
    // must not crash the card — UTC's date is still a real, if imprecise,
    // "today" to key a refetch on.
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "UTC",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(at);
  }
}

/** The receiver-local "today" string, re-derived every {@link POLL_INTERVAL_MS}
 * and whenever `timezone` itself changes. A component reading this value in a
 * TanStack Query key (`analyticsQueryKeys.summary`) gets a fresh query the
 * moment receiver-local midnight passes, without polling the summary
 * endpoint itself any more often than its own `staleTime` already does. */
export function useReceiverLocalDate(timezone: string): string {
  // A changed `timezone` is adjusted for during render (React's documented
  // pattern for state that must track a prop) rather than in an effect, so
  // the corrected date is available on the very render that receives the new
  // zone instead of one render behind it.
  const [tracked, setTracked] = useState(() => ({
    timezone,
    date: receiverLocalDate(timezone),
  }));
  if (tracked.timezone !== timezone) {
    setTracked({ timezone, date: receiverLocalDate(timezone) });
  }

  useEffect(() => {
    const id = window.setInterval(() => {
      setTracked((previous) => ({
        ...previous,
        date: receiverLocalDate(previous.timezone),
      }));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  return tracked.date;
}
