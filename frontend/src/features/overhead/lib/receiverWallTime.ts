/**
 * Receiver-local wall time <-> UTC instants, for the "What was that?" time
 * picker (roadmap slice 090).
 *
 * SPEC §15 puts every displayed time on the receiver's clock, so the picker
 * shows and accepts the receiver's wall time — an `<input
 * type="datetime-local">` value, `YYYY-MM-DDTHH:mm` — whatever zone the
 * browser happens to be in. The API speaks UTC only (`docs/API.md` §2.2), so
 * what the user picks is converted here, with `Intl` doing the zone
 * arithmetic (no timezone library ships with the app).
 *
 * A wall time that does not exist (the hour skipped when clocks go forward)
 * resolves to the instant the same offset arithmetic lands on, and one that
 * happens twice (the repeated hour) to the first — the usual convention, and
 * harmless for a ±N-minute lookup.
 */

const WALL_TIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;

/** The wall-clock fields of `instant` in `timezone`, as a UTC epoch. */
function wallClockAsUtc(instant: number, timezone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(instant));
  const get = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((part) => part.type === type)?.value ?? "0");
  return Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour"),
    get("minute"),
    get("second"),
  );
}

/** `timezone`'s offset from UTC at `instant`, in milliseconds. */
function offsetAt(instant: number, timezone: string): number {
  const whole = Math.floor(instant / 1000) * 1000;
  return wallClockAsUtc(whole, timezone) - whole;
}

/**
 * `iso` as the receiver's wall time, `YYYY-MM-DDTHH:mm` — a
 * `datetime-local` input's value. Falls back to UTC for a zone `Intl` does
 * not know, rather than throwing mid-render.
 */
export function toWallTimeInput(iso: string, timezone: string): string {
  const instant = new Date(iso).getTime();
  let wall: number;
  try {
    wall = wallClockAsUtc(instant, timezone);
  } catch {
    wall = instant;
  }
  return new Date(wall).toISOString().slice(0, 16);
}

/**
 * A `datetime-local` value read as the receiver's wall time, as a UTC ISO
 * instant — or `null` for an empty or malformed value.
 */
export function wallTimeInputToIso(
  value: string,
  timezone: string,
): string | null {
  const match = WALL_TIME_PATTERN.exec(value);
  if (!match) {
    return null;
  }
  const [, year, month, day, hour, minute] = match.map(Number) as [
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  const asUtc = Date.UTC(year, month - 1, day, hour, minute);
  if (Number.isNaN(asUtc)) {
    return null;
  }
  try {
    // Two passes: the offset at the first guess can differ from the offset
    // at the answer when a DST change lies between them.
    const first = asUtc - offsetAt(asUtc, timezone);
    return new Date(asUtc - offsetAt(first, timezone)).toISOString();
  } catch {
    return new Date(asUtc).toISOString();
  }
}
