/**
 * Turns an alert activity event into the text of one browser notification
 * (SPEC §48, roadmap slice 040).
 *
 * SPEC §48 names the payload exactly — *"include useful information
 * (callsign/tail, aircraft type, classification, altitude, distance, match
 * reason)"* — and slice 038's `alert_events()` producer
 * (`backend/src/flightsite/activity/producers.py`) ships every one of those
 * fields on the `alert_triggered` / `emergency_squawk` payload. This module is
 * the whole mapping from that payload to a title and a body, kept pure so the
 * wording is testable without a browser, a socket, or a permission.
 *
 * **Only aircraft data crosses this boundary.** `docs/SECURITY.md` §5:
 * *"Notification content includes aircraft data only — never secrets or
 * configuration"*. Every field read here is named explicitly below; nothing
 * reads the config document, and nothing forwards an unrecognised payload key
 * into the text.
 *
 * **Wording follows the feed, not a second voice.** `reason` is the alert
 * engine's own sentence for the match ("Rule: Military aircraft", "Emergency
 * squawk 7700 (general emergency)"), and it is passed through rather than
 * reworded — the same choice, for the same reason, that
 * `features/activity/lib/describeActivityEvent.ts` documents: it names a rule
 * the *user* wrote, so a notification and the feed row about the same match
 * must not drift apart.
 *
 * Every field degrades. `payload` arrives as `Record<string, unknown>` from a
 * WebSocket frame validated no further than its envelope, so an absent or
 * wrong-typed value drops out of the text instead of rendering `undefined`.
 */

import {
  formatAltitude,
  formatDistance,
} from "@/features/aircraft-detail/lib/format";
import type { ActivityEvent } from "@/lib/api/activity";
import type { UnitSystem } from "@/lib/api/config";
import type { AlertSeverity } from "@/lib/api/sightings";

/** The two `docs/API.md` §3.9 event types slice 038 emits for a recorded
 * alert match. Every other activity type is somebody else's event and never
 * becomes a notification. */
const ALERT_EVENT_TYPES = new Set(["alert_triggered", "emergency_squawk"]);

/** One notification, ready to hand to the browser. */
export interface AlertNotificationContent {
  title: string;
  body: string;
  /**
   * The OS-level collapse key, `flightsite-alert-{event id}`.
   *
   * Deliberately derived from the event id, which is stable across clients:
   * two FlightSite tabs open on the same receiver both fire for the same
   * match, and a shared tag means the user sees **one** notification rather
   * than one per tab. Within a single tab the id is also the dedupe key
   * (`lib/dedupe.ts`), so the tag is a second, independent line of defence
   * for the SPEC §48 "once per sighting per rule" guarantee.
   */
  tag: string;
  /** The airframe to select when the notification is clicked; `null` for an
   * alert the backend could not attribute to an ICAO address. */
  icao: string | null;
  severity: AlertSeverity;
  /**
   * The `alert_matches` row this notification is about (`docs/API.md` §3.10),
   * or `null` when the event carries no `match_id` — an older backend, or a
   * payload that lost the key on its way here.
   *
   * Read out here rather than in `dispatch.ts` because this module is already
   * the whole mapping from an open `payload` to typed values, and because a
   * `null` has to mean "do not report" rather than "report zero" — which a
   * caller reaching into `payload` itself would have to re-derive.
   */
  matchId: number | null;
}

type Payload = Record<string, unknown>;

function str(payload: Payload, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function num(payload: Payload, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function join(
  parts: readonly (string | null)[],
  separator = " · ",
): string | null {
  const present = parts.filter((part): part is string => part !== null);
  return present.length === 0 ? null : present.join(separator);
}

/**
 * What to call this aircraft: callsign, else tail, else the ICAO address.
 *
 * Callsign first because it is what the user sees on the map label and what
 * air traffic control says out loud; the ICAO hex is the last resort that
 * guarantees the notification always names *something* (`docs/API.md` §2.7 —
 * unknown is `null`, never a blank string).
 */
function identity(payload: Payload, icao: string | null): string {
  return (
    str(payload, "callsign") ??
    str(payload, "registration") ??
    (icao === null ? null : icao.toUpperCase()) ??
    str(payload, "icao")?.toUpperCase() ??
    "Unknown aircraft"
  );
}

/** SPEC §48's "aircraft type": the resolved model, qualified by its type code
 * when both are known (`"B77W · Boeing 777-300ER"`). */
function aircraftType(payload: Payload): string | null {
  const typeCode = str(payload, "type_code");
  const model = str(payload, "model");
  if (typeCode !== null && model !== null) {
    return `${typeCode} · ${model}`;
  }
  return model ?? typeCode;
}

/**
 * SPEC §48's "classification": the operator-category flags slice 038 resolves,
 * as words.
 *
 * All three can be true at once (a government law-enforcement aircraft), so
 * they are listed rather than collapsed to the first hit — the classification
 * is *why* many rules fire, and dropping part of it would make the
 * notification disagree with the reason beside it.
 */
function classification(payload: Payload): string | null {
  return join(
    [
      payload.military === true ? "Military" : null,
      payload.government === true ? "Government" : null,
      payload.law_enforcement === true ? "Law enforcement" : null,
    ],
    ", ",
  );
}

/**
 * The headline half of the title.
 *
 * An emergency squawk leads with the code, because SPEC §47 wants these
 * *prominent* rather than one alert among many and the code is the fact that
 * makes it so — the fuller `reason` then moves into the body. Every other
 * alert leads with the match reason itself, falling back to the rule's name
 * and finally to a bare label for a payload carrying neither.
 */
function headline(event: ActivityEvent, payload: Payload): string {
  if (event.type === "emergency_squawk") {
    const squawk = str(payload, "squawk");
    return squawk === null ? "Emergency squawk" : `Emergency squawk ${squawk}`;
  }
  return str(payload, "reason") ?? str(payload, "rule_name") ?? "Alert";
}

/**
 * The notification for one alert event, or `null` when the event is not an
 * alert at all.
 *
 * `units` is the receiver's display preference (`docs/API.md` §3.2): the wire
 * is always nm/ft (`CLAUDE.md`), and the conversion happens here so a metric
 * install reads a metric notification.
 */
export function composeAlertNotification(
  event: ActivityEvent,
  units: UnitSystem,
): AlertNotificationContent | null {
  if (!ALERT_EVENT_TYPES.has(event.type)) {
    return null;
  }
  const payload = event.payload;
  const name = identity(payload, event.icao);
  const lead = headline(event, payload);

  // The reason is already the headline for a rule match, so repeating it in
  // the body would fill a two-line notification with one sentence twice.
  const reason =
    event.type === "emergency_squawk" ? str(payload, "reason") : null;
  const tail = str(payload, "registration");

  const body =
    join(
      [
        reason,
        join([
          tail === name ? null : tail,
          aircraftType(payload),
          str(payload, "operator"),
        ]),
        classification(payload),
        join([
          formatDistance(num(payload, "distance_nm"), units),
          formatAltitude(num(payload, "altitude_ft"), units),
        ]),
      ],
      "\n",
    ) ?? "";

  return {
    title: `${name} · ${lead}`,
    body,
    tag: `flightsite-alert-${event.id}`,
    icao: event.icao,
    severity: event.severity,
    matchId: num(payload, "match_id"),
  };
}
