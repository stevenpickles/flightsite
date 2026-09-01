import { render, screen } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { ConnectionStatusChip } from "@/features/map/aircraft/ConnectionStatusChip";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";

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
});
