import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WatchlistsSection } from "@/features/watchlists/components/WatchlistsSection";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { renderWithProviders } from "@/test/test-utils";
import {
  installWatchlistsApiMock,
  watchlist,
  watchlistEntry,
} from "@/test/watchlistsApiMock";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WatchlistsSection", () => {
  it("shows an empty state when there are no watchlists", async () => {
    installWatchlistsApiMock();
    renderWithProviders(<WatchlistsSection />);

    expect(await screen.findByText(/no watchlists yet/i)).toBeInTheDocument();
  });

  it("lists existing watchlists with their entry count", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Police Helicopters" })],
      entriesByWatchlistId: {
        1: [
          watchlistEntry({ id: 1, watchlist_id: 1, value: "AAAAAA" }),
          watchlistEntry({ id: 2, watchlist_id: 1, value: "BBBBBB" }),
          watchlistEntry({ id: 3, watchlist_id: 1, value: "CCCCCC" }),
        ],
      },
    });
    renderWithProviders(<WatchlistsSection />);

    expect(await screen.findByText("Police Helicopters")).toBeInTheDocument();
    expect(screen.getByText(/3 entries/)).toBeInTheDocument();
  });

  it("creates a watchlist and shows it in the list", async () => {
    installWatchlistsApiMock();
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText(/no watchlists yet/i);
    await user.type(screen.getByLabelText("Name"), "Local Police");
    await user.click(screen.getByRole("button", { name: /create watchlist/i }));

    expect(await screen.findByText("Local Police")).toBeInTheDocument();
    expect(screen.getByText(/0 entries/)).toBeInTheDocument();
  });

  it("rejects creating a watchlist with a blank name", async () => {
    installWatchlistsApiMock();
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText(/no watchlists yet/i);
    await user.click(screen.getByRole("button", { name: /create watchlist/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(screen.queryByText(/no watchlists yet/i)).toBeInTheDocument();
  });

  it("surfaces a duplicate watchlist name from the backend", async () => {
    installWatchlistsApiMock({ watchlists: [watchlist({ name: "Taken" })] });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Taken");
    await user.type(screen.getByLabelText("Name"), "Taken");
    await user.click(screen.getByRole("button", { name: /create watchlist/i }));

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
  });

  it("expands a watchlist to show its entries and adds one", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Rare Types" })],
    });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Rare Types");
    await user.click(screen.getByRole("button", { name: /show entries/i }));
    await user.selectOptions(await screen.findByLabelText("Kind"), "type_code");
    await user.type(screen.getByLabelText("Value"), "b738");
    await user.click(screen.getByRole("button", { name: /add entry/i }));

    expect(await screen.findByText("B738")).toBeInTheDocument();
    // Adding an entry refreshes the watchlist list's own entry_count too.
    expect(await screen.findByText(/1 entry\b/)).toBeInTheDocument();
  });

  it("rejects an invalid value for the selected kind before submitting", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Rare Types" })],
    });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Rare Types");
    await user.click(screen.getByRole("button", { name: /show entries/i }));
    await user.type(await screen.findByLabelText("Value"), "not-hex");
    await user.click(screen.getByRole("button", { name: /add entry/i }));

    expect(await screen.findByText(/six hex digits/i)).toBeInTheDocument();
  });

  it("offers a category picklist instead of free text for the category kind", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "By Category" })],
    });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("By Category");
    await user.click(screen.getByRole("button", { name: /show entries/i }));
    await user.selectOptions(await screen.findByLabelText("Kind"), "category");
    await user.selectOptions(screen.getByLabelText("Value"), "military");
    await user.click(screen.getByRole("button", { name: /add entry/i }));

    expect(await screen.findByText("MILITARY")).toBeInTheDocument();
  });

  it("removes an entry", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Rare Types", entry_count: 1 })],
      entriesByWatchlistId: {
        1: [
          watchlistEntry({
            id: 9,
            watchlist_id: 1,
            kind: "type_code",
            value: "B738",
          }),
        ],
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Rare Types");
    await user.click(screen.getByRole("button", { name: /show entries/i }));
    await screen.findByText(/B738/);

    await user.click(
      screen.getByRole("button", { name: /remove aircraft type entry b738/i }),
    );

    await waitFor(() =>
      expect(screen.queryByText(/B738/)).not.toBeInTheDocument(),
    );
  });

  it("renames a watchlist", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Old Name" })],
    });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Old Name");
    await user.click(screen.getByRole("button", { name: /rename/i }));
    const renameForm = within(
      screen.getByRole("form", { name: /rename old name/i }),
    );
    const nameField = renameForm.getByLabelText("Name");
    await user.clear(nameField);
    await user.type(nameField, "New Name");
    await user.click(renameForm.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText("New Name")).toBeInTheDocument();
    expect(screen.queryByText("Old Name")).not.toBeInTheDocument();
  });

  it("rejects renaming to a blank name without submitting", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Old Name" })],
    });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Old Name");
    await user.click(screen.getByRole("button", { name: /rename/i }));
    const renameForm = within(
      screen.getByRole("form", { name: /rename old name/i }),
    );
    await user.clear(renameForm.getByLabelText("Name"));
    await user.click(renameForm.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    // Still in the rename form — nothing was submitted.
    expect(
      screen.getByRole("form", { name: /rename old name/i }),
    ).toBeInTheDocument();
  });

  it("surfaces a server-side rename collision and lets the user cancel out", async () => {
    installWatchlistsApiMock({
      watchlists: [
        watchlist({ id: 1, name: "First" }),
        watchlist({ id: 2, name: "Second" }),
      ],
    });
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Second");
    const secondCard = screen.getByText("Second").closest("article");
    if (!secondCard) {
      throw new Error("expected the Second watchlist's card to render");
    }
    await user.click(
      within(secondCard).getByRole("button", { name: /rename/i }),
    );
    const renameForm = within(
      screen.getByRole("form", { name: /rename second/i }),
    );
    await user.clear(renameForm.getByLabelText("Name"));
    await user.type(renameForm.getByLabelText("Name"), "First");
    await user.click(renameForm.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();

    await user.click(renameForm.getByRole("button", { name: /cancel/i }));

    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  it("deletes a watchlist after confirming", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Gone Soon" })],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Gone Soon");
    await user.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() =>
      expect(screen.queryByText("Gone Soon")).not.toBeInTheDocument(),
    );
    expect(await screen.findByText(/no watchlists yet/i)).toBeInTheDocument();
  });

  it("keeps a watchlist when the delete confirmation is declined", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Staying Put" })],
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderWithProviders(<WatchlistsSection />);

    await screen.findByText("Staying Put");
    await user.click(screen.getByRole("button", { name: /delete/i }));

    expect(screen.getByText("Staying Put")).toBeInTheDocument();
  });

  it("shows the live match count from the live store's flagged aircraft", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Police Helicopters" })],
    });
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [
          makeAircraft({ icao: "aaaaaa", watchlists: ["Police Helicopters"] }),
          makeAircraft({ icao: "bbbbbb", watchlists: ["Police Helicopters"] }),
          makeAircraft({ icao: "cccccc", watchlists: [] }),
        ],
        receiver: null,
      });
    });
    renderWithProviders(<WatchlistsSection />);

    expect(await screen.findByText(/2 live matches/)).toBeInTheDocument();
  });

  it("shows a load error without crashing the section", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("boom", { status: 500 })),
    );
    renderWithProviders(<WatchlistsSection />);

    expect(
      await screen.findByText(/could not load watchlists/i),
    ).toBeInTheDocument();
  });
});
