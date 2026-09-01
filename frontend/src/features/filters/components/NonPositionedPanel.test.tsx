import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { NonPositionedPanel } from "@/features/filters/components/NonPositionedPanel";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  resetFilteredLiveAircraftCache();
  useLiveAircraftStore.getState().reset();
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
});

function seed() {
  act(() => {
    useLiveAircraftStore.getState().applySnapshot({
      aircraft: [
        makeAircraft({
          icao: "aaaaaa",
          callsign: "RCH471",
          position: null,
          distance_nm: null,
          altitude_ft: 5000,
          squawk: "7000",
          rssi_db: -12.3,
        }),
        makeAircraft({
          icao: "bbbbbb",
          callsign: "UAL45",
          position: { lat: 47, lon: -122 },
        }),
      ],
      receiver: null,
    });
  });
}

describe("NonPositionedPanel", () => {
  it("shows a count badge for non-positioned aircraft, excluding positioned ones", () => {
    seed();
    render(<NonPositionedPanel />);
    expect(screen.getByTestId("non-positioned-count")).toHaveTextContent("1");
  });

  it("starts collapsed and expands to list the aircraft on click", async () => {
    seed();
    render(<NonPositionedPanel />);
    expect(screen.queryByText("RCH471")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /non-positioned/i }),
    );
    expect(screen.getByText("RCH471")).toBeInTheDocument();
    expect(screen.getByText(/5000 ft/)).toBeInTheDocument();
    expect(screen.getByText(/7000/)).toBeInTheDocument();
    expect(screen.getByText(/-12.3 dB/)).toBeInTheDocument();
    // The positioned aircraft never appears in this list.
    expect(screen.queryByText("UAL45")).not.toBeInTheDocument();
  });

  it("selects the aircraft on click, same as a map click would", async () => {
    seed();
    render(<NonPositionedPanel />);
    await userEvent.click(
      screen.getByRole("button", { name: /non-positioned/i }),
    );
    await userEvent.click(screen.getByText("RCH471"));
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");
  });

  it("is hidden entirely when hide-non-positioned is on", () => {
    seed();
    useFilterStore.getState().setHideNonPositioned(true);
    render(<NonPositionedPanel />);
    expect(
      screen.queryByTestId("non-positioned-panel"),
    ).not.toBeInTheDocument();
  });

  it("shows an empty state when the live set has no non-positioned aircraft", async () => {
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "bbbbbb" })],
        receiver: null,
      });
    });
    render(<NonPositionedPanel />);
    expect(screen.getByTestId("non-positioned-count")).toHaveTextContent("0");
    await userEvent.click(
      screen.getByRole("button", { name: /non-positioned/i }),
    );
    expect(screen.getByText(/no non-positioned aircraft/i)).toBeInTheDocument();
  });
});
