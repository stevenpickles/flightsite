import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrackStats } from "@/features/aircraft-detail/components/TrackStats";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

describe("TrackStats", () => {
  it("shows a quiet message when nothing has accumulated yet", () => {
    render(<TrackStats points={[]} />);
    expect(screen.getByText(/No track accumulated yet/i)).toBeInTheDocument();
  });

  it("shows point count and duration for an accumulated track", () => {
    render(
      <TrackStats
        points={[
          { lat: 47, lon: -122, at: 0 },
          { lat: 47.1, lon: -122, at: 3000 },
          { lat: 47.2, lon: -122, at: 12000 },
        ]}
      />,
    );
    expect(screen.getByText(/3 points/)).toBeInTheDocument();
    expect(screen.getByText(/12s since selection/)).toBeInTheDocument();
  });

  it("uses singular wording for exactly one point", () => {
    render(<TrackStats points={[{ lat: 47, lon: -122, at: 0 }]} />);
    expect(screen.getByText(/1 point\b/)).toBeInTheDocument();
  });

  it("times a backfilled track from the selection, not from the sighting", () => {
    // The regression this pins: reading the duration off the *drawn* track
    // made a click on a 20-minute-old flight report "20m since selection"
    // immediately, and — because re-selecting no longer restarts the track —
    // permanently. The store's `trackLive` is the only list the selection
    // actually dates.
    const T0 = 1_800_000_000_000;
    const store = useLiveAircraftStore.getState();
    store.reset();
    store.applySnapshot(
      {
        aircraft: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47.5, lon: -122 } }),
        ],
        receiver: null,
      },
      T0,
    );
    store.selectAircraft("aaaaaa", T0);
    store.backfillTrack("aaaaaa", 91_001, [
      { lat: 47.1, lon: -122, at: T0 - 1_200_000 },
      { lat: 47.3, lon: -122, at: T0 - 600_000 },
    ]);
    store.applyDelta(
      {
        updated: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47.6, lon: -122 } }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 5000,
    );

    // Twenty minutes of track is drawn, two positions of it were watched.
    expect(useLiveAircraftStore.getState().track?.points).toHaveLength(4);
    render(<TrackStats points={useLiveAircraftStore.getState().trackLive} />);

    expect(
      screen.getByText(/2 points · 5s since selection/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/20m/)).not.toBeInTheDocument();

    useLiveAircraftStore.getState().reset();
  });
});
