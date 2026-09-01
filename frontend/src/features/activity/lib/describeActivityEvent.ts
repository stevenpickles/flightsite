/**
 * Plain-language labels for the activity feed (SPEC §55) — one entry per
 * `docs/API.md` §3.9 event type, plus every `receiver_record` and `milestone`
 * sub-kind.
 *
 * **This module is where the English lives, and that is deliberate.** The
 * backend ships structured payloads — `{range_nm: 412.75, previous_nm: 401.2}`
 * — rather than sentences, because a stored sentence is a stored rendering
 * decision: it cannot be re-worded, re-ordered or translated after the fact,
 * and it would freeze a formatting choice into a table retained indefinitely
 * (`docs/DATA_MODEL.md` §11). So the row's wording is a pure function of the
 * event, computed here, mirroring `features/sighting-detail/lib/eventDescriptions.ts`.
 *
 * Every path degrades rather than throws. `payload` arrives as
 * `Record<string, unknown>` — from a REST page or, unvalidated beyond its
 * envelope, from a WebSocket frame — so nothing here indexes into it without
 * checking the type it got back, and a missing field drops out of the detail
 * line instead of rendering `undefined`. An event type this build has never
 * heard of still produces a readable label from its own slug, which is what
 * lets a client survive a backend that has learned to say something new (§6).
 */

import type { ActivityEvent } from "@/lib/api/activity";
import { formatSightingDuration } from "@/features/sightings/lib/format";
import { cardinalFromDegrees } from "@/features/receiver/lib/format";

export interface ActivityDescription {
  /** The row's headline. Never empty. */
  label: string;
  /** The secondary line, or `null` when the event has nothing to add. */
  detail: string | null;
}

type Payload = Record<string, unknown>;

function str(payload: Payload, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function num(payload: Payload, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function bool(payload: Payload, key: string): boolean | null {
  const value = payload[key];
  return typeof value === "boolean" ? value : null;
}

/** Joins the parts of a detail line, dropping every absent one. Returns
 * `null` rather than an empty string so callers never render a blank line. */
function join(
  parts: readonly (string | null)[],
  separator = " · ",
): string | null {
  const present = parts.filter((part): part is string => part !== null);
  return present.length === 0 ? null : present.join(separator);
}

function count(value: number): string {
  return value.toLocaleString();
}

function distance(value: number): string {
  return `${value.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} nm`;
}

/**
 * `"receiver_offline"` -> `"Receiver offline"`.
 *
 * A local four-line helper rather than an import of
 * `features/analytics/lib/format.ts`'s equivalent: the Analytics feature is
 * route-level `lazy` precisely to keep its module graph out of the initial
 * bundle, and reaching into it for one string function would pull a piece of
 * that graph back into the Live Map's chunk.
 */
function humanize(slug: string): string {
  const spaced = slug.replaceAll("_", " ").trim();
  if (spaced.length === 0) {
    return "Activity";
  }
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** The airframe identity line every aircraft-scoped event shares: whichever
 * of registration / model / operator the metadata actually resolved, falling
 * back to the ICAO address so a row about an unknown airframe still names it
 * (`docs/API.md` §2.7 — unknown is `null`, not a blank). */
function airframe(payload: Payload, icao: string | null): string | null {
  const identity =
    str(payload, "registration") ??
    (icao === null ? null : icao.toUpperCase()) ??
    str(payload, "icao")?.toUpperCase() ??
    null;
  return join([identity, str(payload, "model"), str(payload, "operator")]);
}

/** `"412.8 nm (previous 401.2 nm)"`, or just the value when there is no
 * previous — the first record of its kind has nothing to have beaten. */
function beating(
  value: number,
  previous: number | null,
  format: (n: number) => string,
): string {
  return previous === null
    ? format(value)
    : `${format(value)} (previous ${format(previous)})`;
}

function describeRecord(payload: Payload): ActivityDescription {
  switch (str(payload, "record")) {
    case "max_simultaneous": {
      const value = num(payload, "value");
      return {
        label: "New record: most aircraft at once",
        detail:
          value === null
            ? null
            : `${beating(value, num(payload, "previous"), count)} aircraft`,
      };
    }
    case "busiest_day": {
      const value = num(payload, "value");
      const day = str(payload, "day");
      const previousDay = str(payload, "previous_day");
      return {
        label: "New busiest day",
        detail: join([
          day,
          value === null ? null : `${count(value)} messages`,
          previousDay === null ? null : `previous ${previousDay}`,
        ]),
      };
    }
    case "longest_sighting": {
      const seconds = num(payload, "duration_s");
      const previous = num(payload, "previous_s");
      return {
        label: "New longest sighting",
        detail:
          seconds === null
            ? null
            : beating(seconds, previous, formatSightingDuration),
      };
    }
    default:
      // A record kind this build does not know — the `receiver_record` type is
      // open on the backend precisely so a new one is a producer rather than a
      // migration, so the row says what it can and stays.
      return { label: "New receiver record", detail: null };
  }
}

function describeMilestone(
  payload: Payload,
  icao: string | null,
): ActivityDescription {
  switch (str(payload, "kind")) {
    case "unique_aircraft": {
      const threshold = num(payload, "threshold");
      return {
        label:
          threshold === null
            ? "Unique-aircraft milestone"
            : `${count(threshold)}th unique aircraft`,
        detail: airframe(payload, icao),
      };
    }
    case "first_military":
      return {
        label: "First military aircraft ever seen",
        detail: airframe(payload, icao),
      };
    default: {
      // Every milestone carries its natural key (`first_type_B52`,
      // `unique_aircraft_1000`), so even an unrecognised kind has something
      // honest to show.
      const key = str(payload, "key");
      return {
        label: key === null ? "Milestone reached" : humanize(key),
        detail: airframe(payload, icao),
      };
    }
  }
}

export function describeActivityEvent(
  event: ActivityEvent,
): ActivityDescription {
  const { payload, icao } = event;
  switch (event.type) {
    case "first_ever_aircraft":
      return {
        label: "First ever sighting",
        detail: join([airframe(payload, icao), str(payload, "type_code")]),
      };

    case "new_type": {
      const typeCode = str(payload, "type_code");
      return {
        label:
          typeCode === null
            ? "First example of a new type"
            : `New aircraft type: ${typeCode}`,
        detail: airframe(payload, icao),
      };
    }

    case "range_record": {
      const rangeNm = num(payload, "range_nm");
      const bearing = num(payload, "bearing_deg");
      return {
        label: "New maximum range record",
        detail: join([
          rangeNm === null
            ? null
            : beating(rangeNm, num(payload, "previous_nm"), distance),
          bearing === null
            ? null
            : `bearing ${Math.round(bearing)}° ${cardinalFromDegrees(bearing)}`,
        ]),
      };
    }

    case "receiver_record":
      return describeRecord(payload);

    case "milestone":
      return describeMilestone(payload, icao);

    case "receiver_offline": {
      const uptime = num(payload, "uptime_s");
      return {
        label: "Receiver went offline",
        detail: join([
          str(payload, "error"),
          uptime === null ? null : `after ${formatSightingDuration(uptime)} up`,
        ]),
      };
    }

    case "receiver_restored": {
      const outage = num(payload, "outage_s");
      return {
        label: "Receiver back online",
        detail:
          outage === null
            ? null
            : `after ${formatSightingDuration(outage)} offline`,
      };
    }

    case "metadata_updated": {
      const source = str(payload, "source");
      // `ok` is the authoritative outcome; a payload that omits it is treated
      // as a plain update rather than as a failure, so a missing flag never
      // invents an error the backend did not report.
      const failed = bool(payload, "ok") === false;
      const rows = num(payload, "rows_imported");
      const rejected = num(payload, "rows_rejected");
      const label = failed ? "Metadata update failed" : "Metadata updated";
      return {
        label: source === null ? label : `${label}: ${source}`,
        detail: failed
          ? str(payload, "error")
          : join([
              rows === null ? null : `${count(rows)} rows`,
              rejected === null || rejected === 0
                ? null
                : `${count(rejected)} rejected`,
              str(payload, "dataset_version"),
            ]),
      };
    }

    // The two phase-6 types (roadmap slice 039). No producer emits them yet,
    // but they are in the published schema, so the feed already knows how to
    // render one rather than showing a bare slug the day they arrive.
    case "alert_triggered":
      return { label: "Alert triggered", detail: airframe(payload, icao) };

    case "emergency_squawk": {
      const squawk = str(payload, "squawk");
      return {
        label: "Emergency squawk",
        detail: join([
          squawk === null ? null : `Squawk ${squawk}`,
          airframe(payload, icao),
        ]),
      };
    }

    default:
      // Exhaustive over today's vocabulary; this arm exists for a backend that
      // has learned a type this build predates (§6). Rendering the humanized
      // slug is strictly better than rendering nothing.
      return { label: humanize(event.type), detail: null };
  }
}
