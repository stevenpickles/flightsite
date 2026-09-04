/**
 * Owns the live socket for as long as the app shell is mounted (ADR-0015).
 *
 * One socket per tab, opened when the shell mounts and closed when it
 * unmounts — never on a route change. `features/map/aircraft/AircraftLayer`
 * owned it until issue #105, which is why this hook used to live beside the
 * map: alerts are a leave-it-open feature (SPEC §48 asks for delivery "while
 * FlightSite is open in the browser, including background/minimized tabs"),
 * and a connection tied to the Live Map delivered nothing to a tab parked on
 * Analytics. `components/shell/AppShell` mounts it now — every route inside
 * the app chrome, and deliberately not the setup wizard, which renders
 * outside that shell.
 *
 * Frames go straight into the stores through `getState()` — the socket never
 * causes a React render of its own; only the connection-status chip
 * subscribes, and only to that one field.
 *
 * Two stores, because the socket carries two unrelated things (`docs/API.md`
 * §4). `snapshot`/`delta` are the live *picture*: replaced wholesale, and
 * meaningless once the connection is gone. `activity_batch` frames (§4.4) are
 * notifications about durable history, appended to `useActivityFeedStore` so
 * the activity panel and page can show them arriving on whichever route the
 * tab is on — while `GET /api/v1/activity` supplies everything older.
 *
 * **What resets, and when.** A route change resets nothing; that is the whole
 * point of hoisting. A *lost connection* does. Every status other than `live`
 * drops the live picture and the live activity tail, because neither survives
 * an outage honestly: the snapshot that ends it replaces the picture wholesale
 * (§4.5, the only resync there is), and activity frames have no replay at all,
 * so a tail kept across the gap would read as a continuous list with a silent
 * hole in it. The initial `connecting` takes the same path and finds both
 * already empty.
 *
 * What deliberately survives a reconnect is what the socket does not own: the
 * map's selection and its track — `AircraftLayer` clears those when the map
 * itself goes away — and `receiver`, which is configuration the REST API also
 * serves (`lib/api/receiver.ts`) and which the notification composer reads on
 * every route.
 *
 * The events in a batch also go to `dispatchAlertNotification` (slice 040),
 * which turns the two alert event types into a browser notification when the
 * user has asked for one. It is called here rather than downstream of the
 * store because delivery must survive the store's reset on connection loss:
 * "already notified" is a fact about the tab, not about the current
 * connection.
 */

import { useEffect } from "react";

import { useActivityFeedStore } from "@/features/activity/store/useActivityFeedStore";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { dispatchAlertNotification } from "@/features/notifications/lib/dispatch";
import { LiveSocket } from "@/lib/ws/liveSocket";

export function useLiveConnection(): void {
  useEffect(() => {
    const store = useLiveAircraftStore.getState;
    const activity = useActivityFeedStore.getState;
    const socket = new LiveSocket({
      onSnapshot: (data) => {
        store().applySnapshot(data);
      },
      onDelta: (data) => {
        store().applyDelta(data);
      },
      onActivityBatch: (events) => {
        activity().addEvents(events);
        // Per event, unlike the store: a notification is one user-visible
        // thing per event, and `dispatchAlertNotification` decides for itself
        // which of them are worth raising.
        for (const event of events) {
          dispatchAlertNotification(event);
        }
      },
      onStatus: (status) => {
        if (status !== "live") {
          store().dropLivePicture();
          activity().reset();
        }
        store().setConnection(status);
      },
    });
    socket.start();
    return () => {
      socket.stop();
      // The shell is going away, so this is the tab's own teardown rather than
      // an outage: the whole store goes, selection included.
      store().reset();
      activity().reset();
    };
  }, []);
}
