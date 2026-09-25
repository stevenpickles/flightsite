/**
 * One rendered timestamp: receiver-local text, machine-readable instant,
 * and a `title` naming the zone and the UTC instant behind it (review
 * R2-14).
 *
 * Lives here beside `UnknownValue` and the shared formatters, which is
 * where every surface that renders a fact about an aircraft already reaches
 * for its pieces — the tables, the detail routes and the lifetime block all
 * import from this folder.
 *
 * The review audited `main [title]` on all five history routes and got `[]`:
 * no timestamp anywhere carried its zone or its underlying instant, so a
 * reader not sitting at the receiver had no way to know whose clock a cell
 * was on, and a repeated hour around a DST change was undecidable.
 */

import {
  formatReceiverLocalDateTime,
  formatReceiverLocalTime,
  formatReceiverLocalTitle,
} from "@/features/aircraft-detail/lib/format";

export interface ReceiverTimeProps {
  /** UTC ISO-8601 instant, as every `/api/v1` timestamp is (§2.2). */
  iso: string;
  /** IANA zone from `GET /api/v1/receiver` (§3.2). */
  timezone: string;
  /** `"datetime"` (the default) for a cell that may be months old,
   * `"time"` for one whose day is established by its context. */
  format?: "datetime" | "time";
  className?: string;
}

export function ReceiverTime({
  iso,
  timezone,
  format = "datetime",
  className,
}: ReceiverTimeProps) {
  const text =
    format === "time"
      ? formatReceiverLocalTime(iso, timezone)
      : formatReceiverLocalDateTime(iso, timezone);
  return (
    <time
      dateTime={iso}
      title={formatReceiverLocalTitle(iso, timezone)}
      className={className}
    >
      {text}
    </time>
  );
}
