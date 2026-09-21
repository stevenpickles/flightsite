// `act` from `@testing-library/react`, not from `react`: it is the one that
// sets `IS_REACT_ACT_ENVIRONMENT`, which the chip's own age timer needs now
// that it schedules state updates of its own.
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ConnectionStatusChip,
  ESCALATE_AFTER_ATTEMPTS,
} from "@/features/map/aircraft/ConnectionStatusChip";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

/** What a screen reader would actually read out of the live region: its
 * text, minus every `aria-hidden` descendant. */
function announcedText(region: HTMLElement): string {
  const clone = region.cloneNode(true) as HTMLElement;
  for (const hidden of clone.querySelectorAll('[aria-hidden="true"]')) {
    hidden.remove();
  }
  return clone.textContent?.trim() ?? "";
}

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

  it("announces the status word only, never the aircraft count", () => {
    // Issue R1-15: the count changes whenever anything enters or leaves the
    // picture, and inside a live region every one of those changes
    // re-announced the chip — noise that buries the feed dropping.
    render(<ConnectionStatusChip />);
    act(() => {
      useLiveAircraftStore.getState().setConnection("live");
      useLiveAircraftStore
        .getState()
        .applySnapshot({ aircraft: [makeAircraft()], receiver: null });
    });

    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
    for (const node of region.querySelectorAll("span")) {
      expect(node).toHaveAttribute("aria-hidden", "true");
    }
    // Only the status word is left for a screen reader to read.
    expect(announcedText(region)).toBe("Live");
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

describe("ConnectionStatusChip escalation (R1-03, R1-04)", () => {
  it("counts retries while the socket is down", () => {
    render(<ConnectionStatusChip />);
    act(() => {
      useLiveAircraftStore.getState().setConnection("reconnecting", 2);
    });

    const chip = screen.getByRole("status");
    expect(chip).toHaveTextContent("Reconnecting");
    expect(screen.getByTestId("connection-attempt")).toHaveTextContent(
      "attempt 2",
    );
    // The number changes on a timer; a live region that re-reads itself
    // every retry would bury the one announcement that matters.
    expect(screen.getByTestId("connection-attempt")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("escalates past the threshold, whichever state it is stuck in", () => {
    // Issue R1-04: a blocked WebSocket upgrade never leaves `connecting`,
    // so "Connecting" was the whole of what the user was ever told, over a
    // map with no aircraft on it.
    render(<ConnectionStatusChip />);
    act(() => {
      useLiveAircraftStore
        .getState()
        .setConnection("connecting", ESCALATE_AFTER_ATTEMPTS);
    });

    const chip = screen.getByRole("status");
    expect(chip).toHaveTextContent(/live feed unavailable/i);
    expect(chip).toHaveAttribute("data-escalated", "true");
  });

  it("does not escalate on an ordinary blip below the threshold", () => {
    render(<ConnectionStatusChip />);
    act(() => {
      useLiveAircraftStore
        .getState()
        .setConnection("reconnecting", ESCALATE_AFTER_ATTEMPTS - 1);
    });

    const chip = screen.getByRole("status");
    expect(chip).toHaveTextContent("Reconnecting");
    expect(chip).not.toHaveTextContent(/unavailable/i);
  });

  it("dates a picture nobody is feeding any more", () => {
    // Issue R1-03: a kept picture is only honest with its age beside it.
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-09-20T12:00:00Z"));
      render(<ConnectionStatusChip />);
      act(() => {
        useLiveAircraftStore.getState().setConnection("live");
        useLiveAircraftStore
          .getState()
          .applySnapshot({ aircraft: [makeAircraft()], receiver: null });
      });
      expect(
        screen.queryByTestId("connection-last-update"),
      ).not.toBeInTheDocument();

      act(() => {
        useLiveAircraftStore.getState().markPictureStale();
        useLiveAircraftStore.getState().setConnection("reconnecting", 1);
      });
      act(() => {
        // `advanceTimersByTime` moves the mocked clock too, so this lands
        // the tick exactly twelve seconds after the snapshot.
        vi.setSystemTime(new Date("2026-09-20T12:00:11Z"));
        vi.advanceTimersByTime(1_000);
      });

      expect(screen.getByTestId("connection-last-update")).toHaveTextContent(
        "last update 12s ago",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows no age before any picture has ever arrived", () => {
    render(<ConnectionStatusChip />);
    act(() => {
      useLiveAircraftStore.getState().setConnection("connecting", 1);
    });
    expect(
      screen.queryByTestId("connection-last-update"),
    ).not.toBeInTheDocument();
  });

  it("drops the age again once a fallback poll refreshes the picture", () => {
    render(<ConnectionStatusChip />);
    act(() => {
      useLiveAircraftStore.getState().setConnection("reconnecting", 1);
      useLiveAircraftStore.getState().applyFallbackPicture([makeAircraft()]);
    });

    expect(screen.getByRole("status")).toHaveAttribute("data-stale", "false");
    expect(
      screen.queryByTestId("connection-last-update"),
    ).not.toBeInTheDocument();
  });
});
