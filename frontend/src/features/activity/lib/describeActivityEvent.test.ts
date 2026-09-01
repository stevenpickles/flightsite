import { describe, expect, it } from "vitest";

import { describeActivityEvent } from "@/features/activity/lib/describeActivityEvent";
import type { ActivityEvent, ActivityEventType } from "@/lib/api/activity";
import { activityEvent } from "@/test/activityApiMock";

function event(
  type: ActivityEventType,
  payload: Record<string, unknown>,
  overrides: Partial<ActivityEvent> = {},
): ActivityEvent {
  return activityEvent({ type, payload, ...overrides });
}

describe("describeActivityEvent", () => {
  it("names a first-ever sighting by its resolved airframe", () => {
    const { label, detail } = describeActivityEvent(
      event("first_ever_aircraft", {
        registration: "N302DN",
        type_code: "B738",
        model: "Boeing 737-800",
        operator: "Delta Air Lines",
      }),
    );
    expect(label).toBe("First ever sighting");
    expect(detail).toBe("N302DN · Boeing 737-800 · Delta Air Lines · B738");
  });

  it("falls back to the ICAO address when no metadata resolved", () => {
    // §2.7: unknown is `null`, and a row about an unidentified airframe still
    // has to name it — the address is the identity that always exists.
    const { detail } = describeActivityEvent(
      event("first_ever_aircraft", {}, { icao: "a9c2f0" }),
    );
    expect(detail).toBe("A9C2F0");
  });

  it("names a new type by its designator", () => {
    const { label, detail } = describeActivityEvent(
      event("new_type", {
        type_code: "B52",
        model: "Boeing B-52 Stratofortress",
        registration: "60-0001",
      }),
    );
    expect(label).toBe("New aircraft type: B52");
    expect(detail).toBe("60-0001 · Boeing B-52 Stratofortress");
  });

  it("describes a new type with no designator without inventing one", () => {
    const { label } = describeActivityEvent(event("new_type", {}));
    expect(label).toBe("First example of a new type");
  });

  it("describes a range record against the distance it beat", () => {
    const { label, detail } = describeActivityEvent(
      event("range_record", {
        range_nm: 412.75,
        previous_nm: 401.2,
        bearing_deg: 271.4,
      }),
    );
    expect(label).toBe("New maximum range record");
    expect(detail).toBe("412.8 nm (previous 401.2 nm) · bearing 271° W");
  });

  it("describes a first range record, which beat nothing", () => {
    const { detail } = describeActivityEvent(
      event("range_record", { range_nm: 120 }),
    );
    expect(detail).toBe("120.0 nm");
  });

  it.each([
    [
      "max_simultaneous",
      { record: "max_simultaneous", value: 62, previous: 58 },
      "New record: most aircraft at once",
      "62 (previous 58) aircraft",
    ],
    [
      "busiest_day",
      {
        record: "busiest_day",
        day: "2026-08-30",
        value: 148220,
        previous_day: "2026-07-11",
      },
      "New busiest day",
      "2026-08-30 · 148,220 messages · previous 2026-07-11",
    ],
    [
      "longest_sighting",
      { record: "longest_sighting", duration_s: 8040, previous_s: 7080 },
      "New longest sighting",
      "2h 14m (previous 1h 58m)",
    ],
  ])("describes the %s receiver record", (_kind, payload, label, detail) => {
    const description = describeActivityEvent(
      event("receiver_record", payload),
    );
    expect(description.label).toBe(label);
    expect(description.detail).toBe(detail);
  });

  it("still renders a receiver record whose kind this build predates", () => {
    const { label, detail } = describeActivityEvent(
      event("receiver_record", { record: "something_new", value: 3 }),
    );
    expect(label).toBe("New receiver record");
    expect(detail).toBeNull();
  });

  it("describes a unique-aircraft milestone with a grouped threshold", () => {
    const { label, detail } = describeActivityEvent(
      event("milestone", {
        key: "unique_aircraft_1000",
        kind: "unique_aircraft",
        threshold: 1000,
        registration: "G-EZBY",
      }),
    );
    expect(label).toBe("1,000th unique aircraft");
    expect(detail).toBe("G-EZBY");
  });

  it("describes the first-military milestone", () => {
    const { label, detail } = describeActivityEvent(
      event("milestone", {
        key: "first_military",
        kind: "first_military",
        model: "Lockheed C-130",
      }),
    );
    expect(label).toBe("First military aircraft ever seen");
    expect(detail).toBe("AE1463 · Lockheed C-130");
  });

  it("falls back to a milestone's natural key for an unknown kind", () => {
    const { label } = describeActivityEvent(
      event("milestone", { key: "first_type_B52", kind: "first_type" }),
    );
    expect(label).toBe("First type B52");
  });

  it("describes an outage with its reason and the uptime it ended", () => {
    const { label, detail } = describeActivityEvent(
      event("receiver_offline", {
        error: "ConnectError: connection refused",
        uptime_s: 273600,
      }),
    );
    expect(label).toBe("Receiver went offline");
    expect(detail).toBe("ConnectError: connection refused · after 3d 4h up");
  });

  it("describes a restore by how long the outage lasted", () => {
    const { label, detail } = describeActivityEvent(
      event("receiver_restored", { outage_s: 720 }),
    );
    expect(label).toBe("Receiver back online");
    expect(detail).toBe("after 12m 00s offline");
  });

  it("describes a successful metadata import per source", () => {
    const { label, detail } = describeActivityEvent(
      event("metadata_updated", {
        source: "mictronics",
        ok: true,
        rows_imported: 482110,
        rows_rejected: 0,
        dataset_version: "2026-08-01",
      }),
    );
    expect(label).toBe("Metadata updated: mictronics");
    // A zero rejection count is not news; it drops out rather than reading as
    // an assertion that something was rejected.
    expect(detail).toBe("482,110 rows · 2026-08-01");
  });

  it("describes a failed metadata import with the reason", () => {
    const { label, detail } = describeActivityEvent(
      event("metadata_updated", {
        source: "faa",
        ok: false,
        error: "ConnectError: no network",
      }),
    );
    expect(label).toBe("Metadata update failed: faa");
    expect(detail).toBe("ConnectError: no network");
  });

  it("treats a metadata event with no `ok` flag as a plain update", () => {
    // A missing flag must never invent a failure the backend did not report.
    const { label } = describeActivityEvent(
      event("metadata_updated", { source: "airports" }),
    );
    expect(label).toBe("Metadata updated: airports");
  });

  it.each<ActivityEventType>(["alert_triggered", "emergency_squawk"])(
    "renders the alert type %s without a blank or undefined label",
    (type) => {
      const { label } = describeActivityEvent(event(type, {}));
      expect(label).not.toBe("");
      expect(label).not.toContain("undefined");
    },
  );

  it("headlines an alert with the engine's own match reason", () => {
    // `reason` names a rule the *user* wrote. Passing it through rather than
    // re-deriving a sentence keeps the feed, the alert history and the
    // interesting panel saying the same thing about one match.
    const { label, detail } = describeActivityEvent(
      event(
        "alert_triggered",
        {
          reason: "Rule: Military aircraft",
          rule_name: "Military aircraft",
          registration: "05-8153",
          model: "Boeing C-17A Globemaster III",
        },
        { icao: "ae1463" },
      ),
    );
    expect(label).toBe("Alert: Rule: Military aircraft");
    expect(detail).toContain("05-8153");
  });

  it("falls back to the rule name when an alert carries no reason", () => {
    const { label } = describeActivityEvent(
      event("alert_triggered", { rule_name: "Watchlist — Tankers" }),
    );
    expect(label).toBe("Alert: Watchlist — Tankers");
  });

  it("falls back again when an alert names neither", () => {
    const { label } = describeActivityEvent(event("alert_triggered", {}));
    expect(label).toBe("Alert triggered");
  });

  it("puts the squawk code in an emergency's headline", () => {
    // SPEC §47 wants these prominent rather than one entry among the alerts,
    // which is why they get a type of their own.
    const { label, detail } = describeActivityEvent(
      event(
        "emergency_squawk",
        {
          squawk: "7700",
          reason: "Emergency squawk 7700 (general emergency)",
        },
        { icao: "a1b2c3" },
      ),
    );
    expect(label).toBe("Emergency squawk 7700");
    expect(detail).toContain("Emergency squawk 7700 (general emergency)");
  });

  it("still names an emergency whose squawk did not survive the payload", () => {
    const { label } = describeActivityEvent(event("emergency_squawk", {}));
    expect(label).toBe("Emergency squawk");
  });

  it("renders a humanized slug for a type this build predates", () => {
    // §6: the vocabulary may grow. A backend ahead of this client must not
    // produce an empty row.
    const { label, detail } = describeActivityEvent(
      event("maintenance_issue" as ActivityEventType, {}),
    );
    expect(label).toBe("Maintenance issue");
    expect(detail).toBeNull();
  });

  it.each<ActivityEventType>([
    "alert_triggered",
    "first_ever_aircraft",
    "new_type",
    "range_record",
    "receiver_record",
    "emergency_squawk",
    "receiver_offline",
    "receiver_restored",
    "metadata_updated",
    "milestone",
  ])("never renders undefined for a %s with an empty payload", (type) => {
    // The degrade-gracefully sweep: a payload stripped to nothing (a frame
    // this client could not narrow, a producer that shipped less than
    // expected) must still produce readable text.
    const { label, detail } = describeActivityEvent(
      event(type, {}, { icao: null, sighting_id: null }),
    );
    expect(label.length).toBeGreaterThan(0);
    expect(label).not.toContain("undefined");
    expect(label).not.toContain("null");
    if (detail !== null) {
      expect(detail).not.toContain("undefined");
      expect(detail).not.toContain("null");
    }
  });
});
