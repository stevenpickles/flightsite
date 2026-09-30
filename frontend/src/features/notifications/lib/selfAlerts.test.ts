/**
 * Roadmap slice 088: receiver self-alerts become browser notifications on the
 * same path alert matches take — composed from the activity event, gated by
 * the same switches, deduplicated by event id — plus the one toggle the client
 * applies itself (feeder outages).
 *
 * The acceptance criterion, *"a demo decoder outage produces exactly one
 * offline and one restored notification"*, is asserted at this seam against
 * the event pair the backend's demo outage emits
 * (`backend/tests/demo/test_decoder_outage.py` proves it emits exactly that
 * pair).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { describeActivityEvent } from "@/features/activity/lib/describeActivityEvent";
import { composeSelfAlertNotification } from "@/features/notifications/lib/compose";
import { applyServerConfigToNotificationStore } from "@/features/notifications/lib/configSync";
import { resetNotificationDedupe } from "@/features/notifications/lib/dedupe";
import { dispatchAlertNotification } from "@/features/notifications/lib/dispatch";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import type { ActivityEvent } from "@/lib/api/activity";
import { registerNavigator } from "@/lib/navigation";
import { activityEvent } from "@/test/activityApiMock";
import { defaultFlightSiteConfig } from "@/test/configApiMock";
import {
  installNotificationMock,
  lastNotification,
} from "@/test/notificationMock";

const SINCE_MS = 1_790_000_000_000;

function decoderRaised(overrides: Partial<ActivityEvent> = {}): ActivityEvent {
  return activityEvent({
    id: 7001,
    type: "self_alert_raised",
    severity: "high",
    icao: null,
    sighting_id: null,
    payload: {
      condition: "decoder_down",
      since_ms: SINCE_MS,
      duration_s: null,
      minutes: 5,
      error: "Scripted demo outage",
    },
    ...overrides,
  });
}

function decoderRestored(): ActivityEvent {
  return activityEvent({
    id: 7002,
    type: "self_alert_restored",
    severity: "info",
    icao: null,
    sighting_id: null,
    payload: {
      condition: "decoder_down",
      since_ms: SINCE_MS,
      duration_s: 480,
      minutes: 5,
    },
  });
}

function rateRaised(): ActivityEvent {
  return activityEvent({
    id: 7003,
    type: "self_alert_raised",
    severity: "high",
    icao: null,
    sighting_id: null,
    payload: {
      condition: "message_rate",
      since_ms: SINCE_MS,
      duration_s: null,
      rate_msgs_s: 12.4,
      baseline_msgs_s: 96.2,
      share_pct: 40,
      minutes: 15,
      baseline_weeks: 6,
    },
  });
}

function feederEvent(
  type: "feeder_offline" | "feeder_restored",
): ActivityEvent {
  return activityEvent({
    id: type === "feeder_offline" ? 7101 : 7102,
    type,
    severity: type === "feeder_offline" ? "high" : "info",
    icao: null,
    sighting_id: null,
    payload: {
      feeder: "fr24",
      label: "FlightRadar24",
      kind: "fr24",
      since_ms: SINCE_MS,
      outage_s: type === "feeder_offline" ? null : 185,
    },
  });
}

/** The defaults: notifications on, `info` off, `high` on (SPEC §45). */
function defaultsFromConfig(): void {
  applyServerConfigToNotificationStore(defaultFlightSiteConfig());
}

beforeEach(() => {
  resetNotificationDedupe();
  useNotificationStore.getState().reset();
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))),
  );
});

afterEach(() => {
  registerNavigator(null);
  vi.unstubAllGlobals();
  resetNotificationDedupe();
  useNotificationStore.getState().reset();
});

describe("self-alert wording", () => {
  it("says what went wrong with the decoder, and for how long", () => {
    expect(describeActivityEvent(decoderRaised())).toEqual({
      label: "Self-alert: decoder down",
      detail: "disconnected for over 5 min · Scripted demo outage",
    });
    expect(describeActivityEvent(decoderRestored())).toEqual({
      label: "Self-alert cleared: decoder back",
      detail: "lasted 8m 00s",
    });
  });

  it("puts the rate beside this hour's usual rate", () => {
    expect(describeActivityEvent(rateRaised())).toEqual({
      label: "Self-alert: message rate collapsed",
      detail:
        "12 msg/s against a usual 96 msg/s for this hour · below 40% for 15 min",
    });
  });

  it("degrades for a condition this build predates", () => {
    const event = decoderRaised({
      payload: { condition: "antenna_on_fire", duration_s: null },
    });
    expect(describeActivityEvent(event)).toEqual({
      label: "Self-alert raised",
      detail: "Antenna on fire",
    });
  });
});

describe("composeSelfAlertNotification", () => {
  it("composes a raise from the feed's own wording, pointing at Health", () => {
    const content = composeSelfAlertNotification(decoderRaised(), false);
    expect(content).toEqual({
      title: "Self-alert: decoder down",
      body: "disconnected for over 5 min · Scripted demo outage",
      tag: "flightsite-self-alert-7001",
      icao: null,
      severity: "high",
      matchId: null,
      path: "/health",
    });
  });

  it("gates a restore at the raise's severity, not the feed's info", () => {
    expect(
      composeSelfAlertNotification(decoderRestored(), false)?.severity,
    ).toBe("high");
  });

  it("notifies feeder outages only while their toggle is on", () => {
    expect(
      composeSelfAlertNotification(feederEvent("feeder_offline"), false),
    ).toBeNull();
    expect(
      composeSelfAlertNotification(feederEvent("feeder_offline"), true)?.title,
    ).toBe("Self-alert: FlightRadar24 offline");
    const restored = composeSelfAlertNotification(
      feederEvent("feeder_restored"),
      true,
    );
    expect(restored?.title).toBe("Self-alert cleared: FlightRadar24 back");
    expect(restored?.body).toBe("Down for 3m 05s");
  });

  it("ignores everything else", () => {
    expect(composeSelfAlertNotification(activityEvent(), true)).toBeNull();
    expect(
      composeSelfAlertNotification(
        activityEvent({ type: "receiver_offline" }),
        true,
      ),
    ).toBeNull();
  });
});

describe("delivery", () => {
  it("delivers exactly one offline and one restored notification per outage", () => {
    installNotificationMock({ permission: "granted" });
    defaultsFromConfig();

    const raised = decoderRaised();
    const restored = decoderRestored();
    // Every frame twice: a reconnect overlapping a frame in flight.
    const outcomes = [raised, raised, restored, restored].map((event) =>
      dispatchAlertNotification(event),
    );

    expect(outcomes).toEqual([
      "delivered",
      "duplicate",
      "delivered",
      "duplicate",
    ]);
    expect(useNotificationStore.getState().delivered).toBe(2);
    expect(lastNotification()?.title).toBe("Self-alert cleared: decoder back");
  });

  it("respects the master switch and the High severity switch", () => {
    installNotificationMock({ permission: "granted" });
    applyServerConfigToNotificationStore(
      defaultFlightSiteConfig({
        notifications: {
          enabled: true,
          info: true,
          interesting: true,
          high: false,
          critical: true,
        },
      }),
    );
    expect(dispatchAlertNotification(decoderRaised())).toBe("muted");
  });

  it("mirrors the feeder toggle from the config document", () => {
    installNotificationMock({ permission: "granted" });
    defaultsFromConfig();
    expect(useNotificationStore.getState().feederSelfAlerts).toBe(true);
    expect(dispatchAlertNotification(feederEvent("feeder_offline"))).toBe(
      "delivered",
    );

    const off = defaultFlightSiteConfig();
    off.self_alerts = { ...off.self_alerts!, feeder_offline_enabled: false };
    applyServerConfigToNotificationStore(off);
    expect(dispatchAlertNotification(feederEvent("feeder_restored"))).toBe(
      "not-an-alert",
    );
  });

  it("treats a backend without self-alerts as feeder notifications off", () => {
    const legacy = defaultFlightSiteConfig();
    delete legacy.self_alerts;
    applyServerConfigToNotificationStore(legacy);
    expect(useNotificationStore.getState().feederSelfAlerts).toBe(false);
  });

  it("opens the Health page when clicked", () => {
    installNotificationMock({ permission: "granted" });
    defaultsFromConfig();
    vi.spyOn(window, "focus").mockImplementation(() => undefined);
    const navigate = vi.fn();
    registerNavigator(navigate);

    dispatchAlertNotification(decoderRaised());
    lastNotification()?.onclick?.();

    expect(navigate).toHaveBeenCalledExactlyOnceWith("/health");
  });
});
