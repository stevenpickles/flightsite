/**
 * "All times America/New_York (EDT)" — one line per page naming whose clock
 * its timestamps are on (review R2-14).
 *
 * SPEC §15 mandates receiver-local display against a configurable timezone,
 * and that part was implemented correctly: with the receiver on
 * `America/New_York` and the browser on `Europe/London`, `/aircraft` showed
 * the receiver's wall clock, five hours from the browser's own. What was
 * missing was any way to *know* that — the strings "America/New_York",
 * "EDT", "UTC" and "GMT" appeared nowhere on any of the five routes. Remote
 * access is a case the product supports, so "whose clock is this?" is a
 * question a reader can genuinely have.
 *
 * Once per page rather than once per row: a zone suffix on every cell would
 * be noise, and every timestamp carries the full instant in its `title`
 * anyway.
 */

import { receiverZoneLabel } from "@/features/aircraft-detail/lib/format";
import { cn } from "@/lib/utils";

export interface TimezoneNoteProps {
  /** The IANA zone from `GET /api/v1/receiver` (§3.2). */
  timezone: string;
  className?: string;
}

export function TimezoneNote({ timezone, className }: TimezoneNoteProps) {
  return (
    <p
      data-testid="timezone-note"
      className={cn("text-xs text-muted-foreground", className)}
    >
      All times {receiverZoneLabel(timezone)} — the receiver&rsquo;s timezone.
    </p>
  );
}
