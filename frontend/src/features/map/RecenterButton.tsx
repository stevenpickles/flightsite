import { LocateFixed } from "lucide-react";
import { useEffect } from "react";

import { useMapInstance } from "@/features/map/MapInstanceContext";
import { useMapCenterRequestStore } from "@/features/map/store/useMapCenterRequestStore";
import type { ReceiverPosition } from "@/features/map/types";

/**
 * "Recentre on the receiver" (roadmap slice 082's `H` shortcut) — both the
 * visible control and the one subscriber to `useMapCenterRequestStore`'s
 * request counter. Rendered as a child of `MapLibreMap` (alongside
 * `AircraftLayer`/`OverlaysLayer`) specifically so `useMapInstance` resolves
 * to the live map: `H`, dispatched from `useKeyboardShortcuts` far away in
 * `AppShell`, only records *that* a recentre was asked for, since nothing
 * outside this subtree can reach the MapLibre instance itself.
 *
 * Positioned beneath the quick-filter chip row, which sits under
 * `ConnectionStatusChip` (`left-3 top-3`) in the top-left corner.
 */
export function RecenterButton({ receiver }: { receiver: ReceiverPosition }) {
  const { map } = useMapInstance();
  const nonce = useMapCenterRequestStore((state) => state.nonce);
  const requestRecenter = useMapCenterRequestStore(
    (state) => state.requestRecenter,
  );

  useEffect(() => {
    // `nonce` starts at 0 and only ever increments on a request — skipping
    // it here is "no request yet", not "a request for the zeroth time".
    if (nonce === 0 || !map) {
      return;
    }
    map.easeTo({ center: [receiver.lon, receiver.lat] });
    // Deliberately keyed on `nonce` alone: this recentres once per request,
    // not once per render or per `receiver`/`map` identity change — the
    // effect reads whatever `receiver` and `map` currently are, without
    // re-running just because either reference changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);

  return (
    <button
      type="button"
      onClick={requestRecenter}
      aria-label="Recentre the map on the receiver"
      title="Recentre on receiver"
      className="pointer-events-auto absolute left-3 top-20 z-10 rounded-full border border-border bg-card/95 p-1.5 text-muted-foreground shadow-sm backdrop-blur-sm outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      <LocateFixed className="size-3.5" aria-hidden="true" />
    </button>
  );
}
