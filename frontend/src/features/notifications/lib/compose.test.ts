import { describe, expect, it } from "vitest";

import { composeAlertNotification } from "@/features/notifications/lib/compose";
import {
  activityEvent,
  alertTriggeredEvent,
  emergencySquawkEvent,
} from "@/test/activityApiMock";

describe("composeAlertNotification", () => {
  it("includes everything SPEC §48 asks a notification to carry", () => {
    const content = composeAlertNotification(alertTriggeredEvent(), "aviation");

    expect(content).not.toBeNull();
    // Callsign/tail and the match reason.
    expect(content?.title).toBe("RCH485 · Rule: Military aircraft");
    // Tail, aircraft type, operator, classification, distance and altitude.
    expect(content?.body).toContain("05-5153");
    expect(content?.body).toContain("C17 · Boeing C-17A Globemaster III");
    expect(content?.body).toContain("United States Air Force");
    expect(content?.body).toContain("Military");
    expect(content?.body).toContain("12.4 nm");
    expect(content?.body).toContain("24,000 ft");
  });

  it("carries the event's own identity for click-through and dedupe", () => {
    const content = composeAlertNotification(
      alertTriggeredEvent({ id: 91, icao: "ae1463" }),
      "aviation",
    );

    expect(content?.icao).toBe("ae1463");
    expect(content?.severity).toBe("high");
    expect(content?.tag).toBe("flightsite-alert-91");
  });

  it("carries the alert match the event names, for the notified marker", () => {
    // Issue #104: the event and the `alert_matches` row are two records of one
    // moment, and the match id is what lets a shown notification report itself.
    expect(
      composeAlertNotification(alertTriggeredEvent(), "aviation")?.matchId,
    ).toBe(9100);
    expect(
      composeAlertNotification(emergencySquawkEvent(), "aviation")?.matchId,
    ).toBe(9200);
  });

  it("reports no match id when the payload carries none", () => {
    // An event from a backend older than the field: absent, not zero.
    const content = composeAlertNotification(
      alertTriggeredEvent({ payload: { match_id: null } }),
      "aviation",
    );

    expect(content?.matchId).toBeNull();
  });

  it("leads an emergency squawk with its code and keeps the reason in the body", () => {
    const content = composeAlertNotification(
      emergencySquawkEvent(),
      "aviation",
    );

    expect(content?.title).toBe("RYR8213 · Emergency squawk 7700");
    expect(
      content?.body.startsWith("Emergency squawk 7700 (general emergency)"),
    ).toBe(true);
  });

  it("does not repeat a rule match's reason in the body", () => {
    const content = composeAlertNotification(alertTriggeredEvent(), "aviation");

    const occurrences = `${content?.title}\n${content?.body}`.split(
      "Rule: Military aircraft",
    ).length;
    expect(occurrences).toBe(2); // one split -> the string appears once
  });

  it("converts distance and altitude for a metric install", () => {
    const content = composeAlertNotification(alertTriggeredEvent(), "metric");

    expect(content?.body).toContain("23.0 km");
    expect(content?.body).toContain("7,315 m");
  });

  it("lists every classification that applies", () => {
    const content = composeAlertNotification(
      alertTriggeredEvent({
        payload: { government: true, law_enforcement: true },
      }),
      "aviation",
    );

    expect(content?.body).toContain("Military, Government, Law enforcement");
  });

  it("falls back through callsign, tail, then the ICAO address", () => {
    const noCallsign = composeAlertNotification(
      alertTriggeredEvent({ payload: { callsign: null } }),
      "aviation",
    );
    expect(noCallsign?.title.startsWith("05-5153 ·")).toBe(true);
    // The tail is the name now, so it is not repeated in the body.
    expect(noCallsign?.body).not.toContain("05-5153 ·");

    const anonymous = composeAlertNotification(
      alertTriggeredEvent({
        payload: { callsign: null, registration: null },
      }),
      "aviation",
    );
    expect(anonymous?.title.startsWith("AE1463 ·")).toBe(true);
  });

  it("drops absent fields instead of rendering them", () => {
    const content = composeAlertNotification(
      alertTriggeredEvent({
        payload: {
          registration: null,
          type_code: null,
          model: null,
          operator: null,
          distance_nm: null,
          altitude_ft: null,
          military: false,
        },
      }),
      "aviation",
    );

    expect(content?.title).toBe("RCH485 · Rule: Military aircraft");
    expect(content?.body).toBe("");
    expect(content?.body).not.toContain("undefined");
    expect(content?.body).not.toContain("null");
  });

  it("survives a payload whose fields are the wrong type", () => {
    const content = composeAlertNotification(
      alertTriggeredEvent({
        payload: {
          callsign: 42,
          distance_nm: "far",
          altitude_ft: Number.NaN,
          military: "yes",
        },
      }),
      "aviation",
    );

    expect(content?.title).toBe("05-5153 · Rule: Military aircraft");
    expect(content?.body).not.toContain("far");
    expect(content?.body).not.toContain("Military");
  });

  it("falls back to the rule name, then to a bare label, for a reasonless match", () => {
    expect(
      composeAlertNotification(
        alertTriggeredEvent({ payload: { reason: null } }),
        "aviation",
      )?.title,
    ).toBe("RCH485 · Military aircraft");

    expect(
      composeAlertNotification(
        alertTriggeredEvent({ payload: { reason: null, rule_name: null } }),
        "aviation",
      )?.title,
    ).toBe("RCH485 · Alert");
  });

  it("names an emergency without a squawk code generically", () => {
    expect(
      composeAlertNotification(
        emergencySquawkEvent({ payload: { squawk: null } }),
        "aviation",
      )?.title,
    ).toBe("RYR8213 · Emergency squawk");
  });

  it("is null for every activity event that is not an alert", () => {
    expect(composeAlertNotification(activityEvent(), "aviation")).toBeNull();
    expect(
      composeAlertNotification(
        activityEvent({ type: "range_record", severity: "interesting" }),
        "aviation",
      ),
    ).toBeNull();
  });
});
