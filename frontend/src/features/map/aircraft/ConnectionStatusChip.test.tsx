import { render, screen } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { ConnectionStatusChip } from "@/features/map/aircraft/ConnectionStatusChip";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

describe("ConnectionStatusChip", () => {
  it("reports the initial connecting state", () => {
    render(<ConnectionStatusChip />);
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
  });

  it("follows the store as the socket connects and drops", () => {
    render(<ConnectionStatusChip />);

    act(() => {
      useLiveAircraftStore.getState().setConnection("live");
    });
    expect(screen.getByRole("status")).toHaveTextContent("Live");

    act(() => {
      useLiveAircraftStore.getState().setConnection("reconnecting");
    });
    const chip = screen.getByRole("status");
    expect(chip).toHaveTextContent("Reconnecting");
    expect(chip).toHaveAttribute("data-status", "reconnecting");
  });

  it("stays visible while healthy", () => {
    // An unchanging map looks the same whether nothing is flying or the feed
    // is gone; the chip is what tells those apart, so it is never hidden.
    act(() => {
      useLiveAircraftStore.getState().setConnection("live");
    });
    render(<ConnectionStatusChip />);
    expect(screen.getByRole("status")).toBeVisible();
  });

  it("announces changes politely rather than interrupting", () => {
    render(<ConnectionStatusChip />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });

  it("shows a live aircraft count once the socket is live", () => {
    render(<ConnectionStatusChip />);
    expect(screen.queryByTestId("live-aircraft-count")).not.toBeInTheDocument();

    act(() => {
      useLiveAircraftStore.getState().setConnection("live");
      useLiveAircraftStore
        .getState()
        .applySnapshot({ aircraft: [makeAircraft()], receiver: null });
    });

    expect(screen.getByTestId("live-aircraft-count")).toHaveTextContent(
      "1 aircraft",
    );
  });

  it("hides the count again once the socket drops", () => {
    render(<ConnectionStatusChip />);
    act(() => {
      useLiveAircraftStore.getState().setConnection("live");
      useLiveAircraftStore
        .getState()
        .applySnapshot({ aircraft: [makeAircraft()], receiver: null });
      useLiveAircraftStore.getState().setConnection("reconnecting");
    });
    expect(screen.queryByTestId("live-aircraft-count")).not.toBeInTheDocument();
  });
});
