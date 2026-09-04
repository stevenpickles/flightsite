/**
 * Socket ownership, asserted from the real route tree (ADR-0015, issue #105).
 *
 * The question this file answers is the one the bug was about: *where* the
 * live connection lives. It drives the whole router — the same shape
 * `src/routes.tsx` builds — rather than a component in isolation, because
 * "one socket per tab, surviving navigation" is a statement about the route
 * tree and nothing smaller can make it.
 *
 * No `fetch` mock, deliberately, matching `routes.test.tsx`: the config query
 * fails, which `RootLayout` treats as "not first-run", and every page's own
 * queries fail with it. None of that touches the socket, which is the point.
 */

import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useActivityFeedStore } from "@/features/activity/store/useActivityFeedStore";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { resetNotificationDedupe } from "@/features/notifications/lib/dedupe";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { alertTriggeredEvent } from "@/test/activityApiMock";
import { installConfigApiMock } from "@/test/configApiMock";
import {
  FakeNotification,
  installNotificationMock,
} from "@/test/notificationMock";
import { renderApp } from "@/test/test-utils";
import { FakeWebSocket, getLastWebSocket } from "@/test/webSocketMock";

const ALL_ON = {
  enabled: true,
  info: true,
  interesting: true,
  high: true,
  critical: true,
};

beforeEach(() => {
  resetNotificationDedupe();
  useLiveAircraftStore.getState().reset();
  useActivityFeedStore.getState().reset();
  useNotificationStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetNotificationDedupe();
  useLiveAircraftStore.getState().reset();
  useActivityFeedStore.getState().reset();
  useNotificationStore.getState().reset();
});

/** Clicks a sidebar link and waits for its page's heading. */
async function navigateTo(label: string): Promise<void> {
  await userEvent.click(screen.getByRole("link", { name: label }));
  await waitFor(() => {
    expect(
      screen.getByRole("heading", { level: 1, name: label }),
    ).toBeInTheDocument();
  });
}

describe("AppShell live-socket ownership", () => {
  it("opens exactly one socket, on the documented path, when the app mounts", () => {
    renderApp("/");

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(getLastWebSocket().url).toMatch(/\/api\/v1\/ws\/live$/);
  });

  it("keeps that one socket across map → analytics → map", async () => {
    renderApp("/");
    const socket = getLastWebSocket();

    await navigateTo("Analytics");
    await navigateTo("Live Map");

    // Not "a socket is open" but "the same one, never torn down": before
    // ADR-0015 leaving the map closed it and returning opened a second.
    expect(FakeWebSocket.instances).toEqual([socket]);
    expect(socket.closed).toBe(false);
  });

  it("delivers an alert as a notification while the tab sits on Analytics", async () => {
    // The whole of issue #105: an alert that fires while the user is not on
    // the Live Map used to reach nothing at all.
    installNotificationMock({ permission: "granted" });
    renderApp("/");
    useNotificationStore.getState().setPreferences(ALL_ON);

    await navigateTo("Analytics");

    const socket = getLastWebSocket();
    act(() => {
      socket.emitFrame({
        type: "snapshot",
        seq: 1,
        data: { aircraft: [], receiver: null },
      });
      socket.emitFrame({
        type: "activity_batch",
        seq: 2,
        data: [alertTriggeredEvent()],
      });
    });

    expect(FakeNotification.instances).toHaveLength(1);
    expect(FakeNotification.instances[0]?.title).toBe(
      "RCH485 · Rule: Military aircraft",
    );
    // And the live tail is there for the activity panel/page too.
    expect(
      useActivityFeedStore.getState().events.map((event) => event.id),
    ).toEqual([5100]);
  });

  it("holds the live picture across a route change", async () => {
    renderApp("/");
    const socket = getLastWebSocket();
    act(() => {
      socket.emitFrame({
        type: "snapshot",
        seq: 1,
        data: {
          aircraft: [],
          receiver: {
            site_name: "Home Roof",
            latitude: 47.6,
            longitude: -122.3,
            antenna_height_ft: null,
            timezone: "UTC",
            units: "aviation",
            display_radius_nm: 250,
            alert_radius_nm: null,
            demo_mode: false,
            t0: null,
          },
        },
      });
    });

    await navigateTo("Sightings");

    // The connection never dropped, so nothing about it was reset — the
    // reset trigger is loss, not navigation.
    expect(useLiveAircraftStore.getState().connection).toBe("live");
    expect(useLiveAircraftStore.getState().receiver?.site_name).toBe(
      "Home Roof",
    );
  });

  it("opens no socket for the setup wizard, which renders outside the shell", async () => {
    // The one place the shell's ownership draws a line: nothing is worth
    // streaming to a receiver that has not been configured yet.
    installConfigApiMock({ firstRun: true });
    renderApp("/setup");

    expect(await screen.findByText(/welcome to flightsite/i)).toBeVisible();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });
});
