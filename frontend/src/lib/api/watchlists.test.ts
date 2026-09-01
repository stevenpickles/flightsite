import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { vi } from "vitest";

import {
  addWatchlistEntry,
  createWatchlist,
  deleteWatchlist,
  getWatchlistEntries,
  getWatchlists,
  removeWatchlistEntry,
  updateWatchlist,
  useAddWatchlistEntryMutation,
  useCreateWatchlistMutation,
  useDeleteWatchlistMutation,
  useRemoveWatchlistEntryMutation,
  useUpdateWatchlistMutation,
  useWatchlistEntriesQuery,
  useWatchlistsQuery,
} from "@/lib/api/watchlists";
import { createQueryWrapper } from "@/test/queryWrapper";
import {
  installWatchlistsApiMock,
  watchlist,
  watchlistEntry,
} from "@/test/watchlistsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getWatchlists", () => {
  it("GETs /api/internal/watchlists and returns the list", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Police" })],
    });

    const response = await getWatchlists();

    expect(response.watchlists).toHaveLength(1);
    expect(response.watchlists[0]?.name).toBe("Police");
  });
});

describe("createWatchlist", () => {
  it("POSTs a name/description and returns the created watchlist", async () => {
    const { fetchMock } = installWatchlistsApiMock();

    const created = await createWatchlist({
      name: "Rare Types",
      description: "notable types",
    });

    expect(created.name).toBe("Rare Types");
    expect(created.description).toBe("notable types");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/internal/watchlists");
    expect(init.method).toBe("POST");
  });

  it("surfaces a duplicate name as a rejected promise", async () => {
    installWatchlistsApiMock({ watchlists: [watchlist({ name: "Taken" })] });

    await expect(createWatchlist({ name: "Taken" })).rejects.toThrow();
  });
});

describe("updateWatchlist", () => {
  it("PUTs the new name/description", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Old" })],
    });

    const updated = await updateWatchlist(1, {
      name: "New",
      description: null,
    });

    expect(updated.name).toBe("New");
  });
});

describe("deleteWatchlist", () => {
  it("DELETEs a watchlist", async () => {
    installWatchlistsApiMock({ watchlists: [watchlist({ id: 1 })] });

    await deleteWatchlist(1);

    const listed = await getWatchlists();
    expect(listed.watchlists).toEqual([]);
  });

  it("rejects for an unknown id", async () => {
    installWatchlistsApiMock();

    await expect(deleteWatchlist(999)).rejects.toThrow();
  });
});

describe("entries", () => {
  it("adds and lists an entry", async () => {
    installWatchlistsApiMock({ watchlists: [watchlist({ id: 1 })] });

    const entry = await addWatchlistEntry(1, {
      kind: "icao24",
      value: "ae1463",
    });
    expect(entry.value).toBe("AE1463");

    const listed = await getWatchlistEntries(1);
    expect(listed.entries).toEqual([entry]);
  });

  it("removes an entry", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, entry_count: 1 })],
      entriesByWatchlistId: { 1: [watchlistEntry({ id: 5, watchlist_id: 1 })] },
    });

    await removeWatchlistEntry(1, 5);

    const listed = await getWatchlistEntries(1);
    expect(listed.entries).toEqual([]);
  });

  it("rejects a duplicate entry", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1 })],
      entriesByWatchlistId: {
        1: [
          watchlistEntry({
            id: 1,
            watchlist_id: 1,
            kind: "icao24",
            value: "AE1463",
          }),
        ],
      },
    });

    await expect(
      addWatchlistEntry(1, { kind: "icao24", value: "ae1463" }),
    ).rejects.toThrow();
  });
});

describe("useWatchlistsQuery", () => {
  it("loads the watchlist list", async () => {
    installWatchlistsApiMock({ watchlists: [watchlist({ name: "Police" })] });

    const { result } = renderHook(() => useWatchlistsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.watchlists[0]?.name).toBe("Police");
  });
});

describe("useWatchlistEntriesQuery", () => {
  it("does not fire while watchlistId is null", () => {
    const { fetchMock } = installWatchlistsApiMock();

    renderHook(() => useWatchlistEntriesQuery(null), {
      wrapper: createQueryWrapper(),
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads entries once given a watchlistId", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1 })],
      entriesByWatchlistId: { 1: [watchlistEntry({ id: 1, watchlist_id: 1 })] },
    });

    const { result } = renderHook(() => useWatchlistEntriesQuery(1), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.entries).toHaveLength(1);
  });
});

describe("mutations invalidate the watchlist list", () => {
  it("useCreateWatchlistMutation refreshes useWatchlistsQuery", async () => {
    installWatchlistsApiMock();

    function useBoth() {
      return {
        query: useWatchlistsQuery(),
        mutation: useCreateWatchlistMutation(),
      };
    }
    const { result } = renderHook(() => useBoth(), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() =>
      expect(result.current.query.data?.watchlists).toEqual([]),
    );

    result.current.mutation.mutate({ name: "New Watchlist" });

    await waitFor(() =>
      expect(
        result.current.query.data?.watchlists.map((entry) => entry.name),
      ).toEqual(["New Watchlist"]),
    );
  });

  it("useUpdateWatchlistMutation refreshes useWatchlistsQuery", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, name: "Old" })],
    });

    function useBoth() {
      return {
        query: useWatchlistsQuery(),
        mutation: useUpdateWatchlistMutation(),
      };
    }
    const { result } = renderHook(() => useBoth(), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() =>
      expect(result.current.query.data?.watchlists[0]?.name).toBe("Old"),
    );

    result.current.mutation.mutate({ watchlistId: 1, input: { name: "New" } });

    await waitFor(() =>
      expect(result.current.query.data?.watchlists[0]?.name).toBe("New"),
    );
  });

  it("useDeleteWatchlistMutation refreshes useWatchlistsQuery", async () => {
    installWatchlistsApiMock({ watchlists: [watchlist({ id: 1 })] });

    function useBoth() {
      return {
        query: useWatchlistsQuery(),
        mutation: useDeleteWatchlistMutation(),
      };
    }
    const { result } = renderHook(() => useBoth(), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() =>
      expect(result.current.query.data?.watchlists).toHaveLength(1),
    );

    result.current.mutation.mutate(1);

    await waitFor(() =>
      expect(result.current.query.data?.watchlists).toHaveLength(0),
    );
  });

  it("useAddWatchlistEntryMutation refreshes the watchlist list's entry_count", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, entry_count: 0 })],
    });

    function useBoth() {
      return {
        query: useWatchlistsQuery(),
        mutation: useAddWatchlistEntryMutation(),
      };
    }
    const { result } = renderHook(() => useBoth(), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() =>
      expect(result.current.query.data?.watchlists[0]?.entry_count).toBe(0),
    );

    result.current.mutation.mutate({
      watchlistId: 1,
      input: { kind: "icao24", value: "ae1463" },
    });

    await waitFor(() =>
      expect(result.current.query.data?.watchlists[0]?.entry_count).toBe(1),
    );
  });

  it("useRemoveWatchlistEntryMutation refreshes the watchlist list's entry_count", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ id: 1, entry_count: 1 })],
      entriesByWatchlistId: { 1: [watchlistEntry({ id: 9, watchlist_id: 1 })] },
    });

    function useBoth() {
      return {
        query: useWatchlistsQuery(),
        mutation: useRemoveWatchlistEntryMutation(),
      };
    }
    const { result } = renderHook(() => useBoth(), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() =>
      expect(result.current.query.data?.watchlists[0]?.entry_count).toBe(1),
    );

    result.current.mutation.mutate({ watchlistId: 1, entryId: 9 });

    await waitFor(() =>
      expect(result.current.query.data?.watchlists[0]?.entry_count).toBe(0),
    );
  });
});
