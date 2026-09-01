/**
 * Owns the live socket for as long as the map is mounted.
 *
 * One socket per mounted map, opened on mount and closed on unmount, with the
 * store reset on the way out so a remount never paints a picture left over from
 * a connection that is gone. Frames go straight into the store through
 * `getState()` — the socket never causes a React render of its own; only the
 * connection-status chip subscribes, and only to that one field.
 */

import { useEffect } from "react";

import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { LiveSocket } from "@/lib/ws/liveSocket";

export function useLiveConnection(): void {
  useEffect(() => {
    const store = useLiveAircraftStore.getState;
    const socket = new LiveSocket({
      onSnapshot: (data) => {
        store().applySnapshot(data);
      },
      onDelta: (data) => {
        store().applyDelta(data);
      },
      onStatus: (status) => {
        store().setConnection(status);
      },
    });
    socket.start();
    return () => {
      socket.stop();
      store().reset();
    };
  }, []);
}
