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
 * point of hoisting. A *lost connection* drops the live activity tail, which
 * does not survive an outage honestly: activity frames have no replay at all,
 * so a tail kept across the gap would read as a continuous list with a silent
 * hole in it. The initial `connecting` takes the same path and finds it
 * already empty.
 *
 * The live *picture* is kept and marked stale instead of dropped — issue
 * R1-03. Clearing it made every panel downstream assert an empty sky for the
 * 1-30 s a reconnect takes: "No interesting aircraft right now",
 * `Non-positioned 0`, and `Registration Unknown` for a registration the
 * detail panel knew a second earlier. An outage is not a fact about the sky,
 * and a picture nobody is feeding is old rather than empty, which is
 * something the UI can say.
 *
 * **The REST fallback.** While the connection is not `live`, this hook polls
 * `GET /api/v1/aircraft/current` — the same §3.3 objects the socket carries,
 * which nothing in the frontend read before this — and applies each answer as
 * the picture. That is what turns a blocked WebSocket upgrade, the single
 * most likely reverse-proxy misconfiguration for this product, from a
 * permanently empty map into a working one that merely updates every
 * {@link LIVE_FALLBACK_POLL_MS} (issue R1-04). The poll stops the moment a
 * snapshot arrives, so a healthy tab never issues one, and the first tick is
 * scheduled rather than immediate on a *first* connect, so an ordinary page
 * load does not race its own socket to the same data.
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
import { getCurrentAircraft } from "@/lib/api/live";
import { LiveSocket } from "@/lib/ws/liveSocket";

/**
 * How often the REST fallback refreshes the picture while the socket is down.
 *
 * Five seconds: slow enough that a Raspberry Pi serving a handful of tabs
 * through a broken proxy is not being asked for the whole live picture at the
 * socket's 1 Hz, fast enough that the age the chip and the panels show stays
 * a number a watcher reads as "current-ish" rather than "abandoned". The
 * socket, when it works, remains the only 1 Hz path.
 */
export const LIVE_FALLBACK_POLL_MS = 5_000;

export function useLiveConnection(): void {
  useEffect(() => {
    const store = useLiveAircraftStore.getState;
    const activity = useActivityFeedStore.getState;

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    // One request at a time. A poll slower than the interval (a Pi under
    // load, a proxy sitting on the connection) would otherwise stack
    // requests on a backend that is already struggling.
    let pollInFlight = false;

    const stopPolling = () => {
      if (pollTimer !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const poll = async () => {
      if (pollInFlight) {
        return;
      }
      pollInFlight = true;
      try {
        const aircraft = await getCurrentAircraft();
        // A snapshot may have landed while this was in flight, and it is
        // the better answer — the socket is a second old, this is not.
        if (store().connection !== "live") {
          store().applyFallbackPicture(aircraft);
        }
      } catch {
        // Nothing to say and nothing to do: the picture stays exactly as
        // stale as it was, and the age the chip shows keeps growing, which
        // is the honest report of a backend that is not answering either.
      } finally {
        pollInFlight = false;
      }
    };

    const startPolling = (immediate: boolean) => {
      if (pollTimer !== null) {
        return;
      }
      if (immediate) {
        void poll();
      }
      pollTimer = setInterval(() => void poll(), LIVE_FALLBACK_POLL_MS);
    };

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
      onStatus: (status, attempt) => {
        if (status === "live") {
          stopPolling();
        } else {
          store().markPictureStale();
          activity().reset();
          // Immediately on a drop — the user is watching a picture that has
          // just stopped moving — but only on a schedule for the very first
          // connect, where the socket normally wins in well under a second
          // and an eager poll would be a wasted request on every page load.
          startPolling(attempt > 0 || status === "reconnecting");
        }
        store().setConnection(status, attempt);
      },
    });
    socket.start();
    return () => {
      stopPolling();
      socket.stop();
      // The shell is going away, so this is the tab's own teardown rather than
      // an outage: the whole store goes, selection included.
      store().reset();
      activity().reset();
    };
  }, []);
}
