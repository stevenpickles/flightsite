import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { DisplayRadiusIndicator } from "@/features/filters/components/DisplayRadiusIndicator";
import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  resetFilteredLiveAircraftCache();
  useLiveAircraftStore.getState().reset();
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
  useMapConfigStore.setState({ config: DEV_PLACEHOLDER_MAP_CONFIG });
});

describe("DisplayRadiusIndicator", () => {
  it("renders nothing when no aircraft are capped", () => {
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "aaaaaa", distance_nm: 50 })],
        receiver: null,
      });
    });
    render(<DisplayRadiusIndicator />);
    expect(
      screen.queryByTestId("display-radius-indicator"),
    ).not.toBeInTheDocument();
  });

  it("shows a count and the effective cap once the cap hides aircraft", () => {
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [
          makeAircraft({ icao: "aaaaaa", distance_nm: 50 }),
          makeAircraft({ icao: "bbbbbb", distance_nm: 400 }),
        ],
        receiver: null,
      });
    });
    render(<DisplayRadiusIndicator />);
    const indicator = screen.getByTestId("display-radius-indicator");
    expect(indicator).toHaveTextContent("1 aircraft beyond 250 nm hidden");
  });

  it("uses the display-radius config value, not always 250", () => {
    useMapConfigStore.setState({
      config: { ...DEV_PLACEHOLDER_MAP_CONFIG, displayRadiusNm: 50 },
    });
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "aaaaaa", distance_nm: 100 })],
        receiver: null,
      });
    });
    render(<DisplayRadiusIndicator />);
    expect(screen.getByTestId("display-radius-indicator")).toHaveTextContent(
      "beyond 50 nm",
    );
  });
});
