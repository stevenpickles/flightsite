import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { useActivityFeedStore } from "@/features/activity/store/useActivityFeedStore";
import { LiveSocket } from "@/lib/ws/liveSocket";
import {
  activityEvent,
  activityList,
  installActivityApiMock,
} from "@/test/activityApiMock";
import { getLastWebSocket } from "@/test/webSocketMock";

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ActivityPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Opens a real `LiveSocket` wired the way `useLiveConnection` wires it, so
 * the live half of these tests goes through the actual protocol client and
 * the actual store rather than through a component-level fake.
 */
function openSocket(): LiveSocket {
  const socket = new LiveSocket({
    onActivityBatch: (events) => {
      useActivityFeedStore.getState().addEvents(events);
    },
  });
  socket.start();
  return socket;
}

beforeEach(() => {
  useActivityFeedStore.getState().reset();
});

afterEach(() => {
  useActivityFeedStore.getState().reset();
});

async function expand(): Promise<void> {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /activity/i }));
}

describe("ActivityPanel", () => {
  it("shows the fetched history once expanded, and links to the full view", async () => {
    installActivityApiMock({
      list: activityList([
        activityEvent({ id: 2, at: "2026-08-31T14:03:22.418Z" }),
        activityEvent({
          id: 1,
          type: "receiver_restored",
          icao: null,
          sighting_id: null,
          at: "2026-08-31T13:00:00.000Z",
          payload: { outage_s: 720 },
        }),
      ]),
    });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByTestId("activity-count")).toHaveTextContent("2"),
    );
    await expand();

    expect(screen.getAllByTestId("activity-row")).toHaveLength(2);
    expect(screen.getByText("First ever sighting")).toBeInTheDocument();
    expect(screen.getByText("Receiver back online")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /view all activity/i }),
    ).toHaveAttribute("href", "/activity");
  });

  it("collapses and expands from the header button", async () => {
    installActivityApiMock({ list: activityList([activityEvent()]) });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("activity-count")).toHaveTextContent("1"),
    );

    const header = screen.getByRole("button", { name: /activity/i });
    // Collapsed by default: a floating card over the map earns its space only
    // when the user asks for it.
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("activity-row")).not.toBeInTheDocument();

    await expand();
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByTestId("activity-row")).toHaveLength(1);

    await userEvent.setup().click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("activity-row")).not.toBeInTheDocument();
  });

  it("appends an event delivered over the activity_batch frame", async () => {
    installActivityApiMock({
      list: activityList([
        activityEvent({ id: 1, at: "2026-08-31T13:00:00.000Z" }),
      ]),
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("activity-count")).toHaveTextContent("1"),
    );
    await expand();

    const socket = openSocket();
    const ws = getLastWebSocket();
    act(() => {
      ws.emitFrame({
        type: "snapshot",
        seq: 1,
        data: { aircraft: [], receiver: null },
      });
      ws.emitFrame({
        type: "activity_batch",
        seq: 2,
        data: [
          {
            id: 9,
            type: "range_record",
            severity: "interesting",
            at: "2026-08-31T15:00:00.000Z",
            icao: null,
            sighting_id: null,
            payload: { range_nm: 412.75, previous_nm: 401.2 },
          },
        ],
      });
    });

    await waitFor(() =>
      expect(screen.getAllByTestId("activity-row")).toHaveLength(2),
    );
    // Newest first: the live event outranks the fetched one by `at`.
    const rows = screen.getAllByTestId("activity-row");
    expect(
      within(rows[0] as HTMLElement).getByText("New maximum range record"),
    ).toBeInTheDocument();
    socket.stop();
  });

  it("shows one row when the same event arrives live and in a fetched page", async () => {
    // A reconnect can overlap a refetch, and both halves are built by the same
    // backend serializer — so the two copies are one row, deduped on `id`.
    const duplicate = activityEvent({ id: 42, at: "2026-08-31T14:03:22.418Z" });
    installActivityApiMock({ list: activityList([duplicate]) });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("activity-count")).toHaveTextContent("1"),
    );

    act(() => {
      useActivityFeedStore.getState().addEvents([duplicate]);
    });
    await expand();

    expect(screen.getAllByTestId("activity-row")).toHaveLength(1);
    expect(screen.getByTestId("activity-count")).toHaveTextContent("1");
  });

  it("says so when the receiver has done nothing worth reporting", async () => {
    installActivityApiMock({ list: activityList([]) });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("activity-count")).toHaveTextContent("0"),
    );
    await expand();

    expect(screen.getByText("Nothing has happened yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("activity-row")).not.toBeInTheDocument();
  });

  it("reports a failed fetch rather than rendering an empty feed", async () => {
    installActivityApiMock({ listStatus: 500 });
    renderPanel();
    await expand();

    await waitFor(() =>
      expect(screen.getByText(/could not load activity/i)).toBeInTheDocument(),
    );
  });
});
