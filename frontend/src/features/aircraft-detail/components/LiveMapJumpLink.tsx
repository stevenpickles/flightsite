/**
 * "This aircraft is live right now" affordance on the non-live detail page
 * (roadmap slice 029). Selecting it in the live store before navigating
 * means the Live Map opens with `AircraftDetailPanel` already showing this
 * aircraft, rather than requiring a second click to find it on the map.
 */

import { Radar } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";

export interface LiveMapJumpLinkProps {
  icao: string;
}

export function LiveMapJumpLink({ icao }: LiveMapJumpLinkProps) {
  const navigate = useNavigate();

  return (
    <button
      type="button"
      onClick={() => {
        useLiveAircraftStore.getState().selectAircraft(icao);
        navigate("/");
      }}
      className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-accent/60 px-2.5 py-1 text-xs font-semibold text-accent transition-colors hover:bg-accent/10"
    >
      <Radar className="size-3.5" aria-hidden="true" />
      Live now — view on map
    </button>
  );
}
