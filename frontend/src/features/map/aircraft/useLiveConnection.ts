/**
 * Owns the live socket for as long as the map is mounted.
 *
 * One socket per mounted map, opened on mount and closed on unmount, with the
 * stores reset on the way out so a remount never paints a picture left over
 * from a connection that is gone. Frames go straight into the stores through
 * `getState()` — the socket never causes a React render of its own; only the
 * connection-status chip subscribes, and only to that one field.
 *
 * Two stores, because the socket carries two unrelated things (`docs/API.md`
 * §4). `snapshot`/`delta` are the live *picture*: replaced wholesale, and
 * meaningless once the connection is gone. `activity` frames (§4.4) are
 * notifications about durable history, appended to `useActivityFeedStore` so
 * `ActivityPanel` can show them arriving while the map is open — while
 * `/activity` reads the same events from the database when it is not. Both
 * stores are reset on unmount for the same reason.
 *
 * An `activity` frame also goes to `dispatchAlertNotification` (slice 040),
 * which turns the two alert event types into a browser notification when the
 * user has asked for one. It is called here rather than downstream of the
 * store because delivery must survive the store's reset on teardown: "already
 * notified" is a fact about the tab, not about the current connection.
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
      onActivity: (event) => {
        activity().addEvent(event);
        dispatchAlertNotification(event);
      },
      onStatus: (status) => {
        store().setConnection(status);
      },
    });
    socket.start();
    return () => {
      socket.stop();
      store().reset();
      activity().reset();
    };
  }, []);
}
