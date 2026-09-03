import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getMetadataStatus,
  hasImportedMetadata,
  triggerMetadataUpdate,
  useMetadataAvailable,
  useMetadataStatusQuery,
  useTriggerMetadataUpdateMutation,
} from "@/lib/api/metadata";
import { installMetadataApiMock, metadataSource } from "@/test/metadataApiMock";
import { createQueryWrapper } from "@/test/queryWrapper";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getMetadataStatus", () => {
  it("GETs /api/internal/metadata/status and returns the sources array", async () => {
    const { fetchMock } = installMetadataApiMock({
      statusSequence: [{ sources: [metadataSource({ name: "mictronics" })] }],
    });

    const response = await getMetadataStatus();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/internal/metadata/status",
      undefined,
    );
    expect(response.sources).toHaveLength(1);
    expect(response.sources[0]?.name).toBe("mictronics");
  });
});

describe("triggerMetadataUpdate", () => {
  it("POSTs /api/internal/metadata/update with no body and returns the trigger envelope", async () => {
    const { fetchMock } = installMetadataApiMock({
      triggerResult: { started: true, already_running: false, started_ms: 42 },
    });

    const response = await triggerMetadataUpdate();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/internal/metadata/update");
    expect(init.method).toBe("POST");
    expect(response).toEqual({
      started: true,
      already_running: false,
      started_ms: 42,
    });
  });
});

describe("useMetadataStatusQuery", () => {
  it("loads the status document", async () => {
    installMetadataApiMock({
      statusSequence: [{ sources: [metadataSource({ name: "faa" })] }],
    });

    const { result } = renderHook(() => useMetadataStatusQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.sources[0]?.name).toBe("faa");
  });

  it("keeps polling on its own while a source is running, until it settles", async () => {
    // A real, uncontrolled poll cycle (`MetadataSection.test.tsx`'s
    // "polls until the run settles" covers that polling actually *stops*
    // once settled, end to end through the component); this checks the
    // hook drives at least one automatic refetch off `refetchInterval`
    // without anything else re-invoking the query.
    installMetadataApiMock({
      statusSequence: [
        {
          sources: [metadataSource({ name: "mictronics", status: "running" })],
        },
        { sources: [metadataSource({ name: "mictronics", status: "ok" })] },
      ],
    });

    const { result } = renderHook(() => useMetadataStatusQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() =>
      expect(result.current.data?.sources[0]?.status).toBe("running"),
    );
    await waitFor(
      () => expect(result.current.data?.sources[0]?.status).toBe("ok"),
      { timeout: 4000 },
    );
  });
});

describe("hasImportedMetadata", () => {
  it("is false with no status document at all", () => {
    expect(hasImportedMetadata(undefined)).toBe(false);
  });

  it("is false for a stock install with no registered sources", () => {
    expect(hasImportedMetadata({ sources: [] })).toBe(false);
  });

  it("is false for a registered source that has never run", () => {
    expect(
      hasImportedMetadata({
        sources: [metadataSource({ name: "mictronics", status: "never-run" })],
      }),
    ).toBe(false);
  });

  it("is false for a source reporting zero rows", () => {
    expect(
      hasImportedMetadata({
        sources: [
          metadataSource({
            name: "mictronics",
            status: "ok",
            row_count: 0,
            last_success_ms: 1_756_600_000_000,
          }),
        ],
      }),
    ).toBe(false);
  });

  it("is true when any one airframe source has rows installed", () => {
    expect(
      hasImportedMetadata({
        sources: [
          metadataSource({ name: "mictronics", status: "never-run" }),
          metadataSource({
            name: "faa",
            status: "ok",
            row_count: 412_003,
            last_success_ms: 1_756_600_000_000,
          }),
        ],
      }),
    ).toBe(true);
  });

  it("ignores the airports source, whose rows are airports rather than airframes", () => {
    // SPEC §27 keeps every source's outcome independent, so this — airports
    // imported, both airframe sources failed — is an ordinary state, and it
    // must not read as "this install has aircraft metadata".
    expect(
      hasImportedMetadata({
        sources: [
          metadataSource({
            name: "airports",
            status: "ok",
            row_count: 80_412,
            last_success_ms: 1_756_600_000_000,
          }),
          metadataSource({
            name: "mictronics",
            status: "failed",
            last_error: "download failed",
          }),
          metadataSource({
            name: "faa",
            status: "failed",
            last_error: "download failed",
          }),
        ],
      }),
    ).toBe(false);
  });

  it("is true for airports alongside an airframe source with rows", () => {
    expect(
      hasImportedMetadata({
        sources: [
          metadataSource({
            name: "airports",
            status: "ok",
            row_count: 80_412,
            last_success_ms: 1_756_600_000_000,
          }),
          metadataSource({
            name: "opensky",
            status: "ok",
            row_count: 512_000,
            last_success_ms: 1_756_600_000_000,
          }),
        ],
      }),
    ).toBe(true);
  });

  it("ignores an unrecognized source name — a new airframe source lands with the code that names it", () => {
    expect(
      hasImportedMetadata({
        sources: [
          metadataSource({
            name: "some-future-source",
            status: "ok",
            row_count: 1_000,
            last_success_ms: 1_756_600_000_000,
          }),
        ],
      }),
    ).toBe(false);
  });

  it("stays true while a later run is in flight or has failed — the installed dataset is still there", () => {
    const installed = {
      row_count: 412_003,
      last_success_ms: 1_756_600_000_000,
      dataset_version: "2026-08-01",
    };
    expect(
      hasImportedMetadata({
        sources: [
          metadataSource({ name: "faa", status: "running", ...installed }),
        ],
      }),
    ).toBe(true);
    expect(
      hasImportedMetadata({
        sources: [
          metadataSource({
            name: "faa",
            status: "failed",
            last_error: "download failed",
            ...installed,
          }),
        ],
      }),
    ).toBe(true);
  });
});

describe("useMetadataAvailable", () => {
  it("reports availability once the status document lands", async () => {
    installMetadataApiMock({
      statusSequence: [
        {
          sources: [
            metadataSource({
              name: "mictronics",
              status: "ok",
              row_count: 412_003,
              last_success_ms: 1_756_600_000_000,
            }),
          ],
        },
      ],
    });

    const { result } = renderHook(() => useMetadataAvailable(), {
      wrapper: createQueryWrapper(),
    });

    // Never the other way round: unavailable until the data says otherwise.
    expect(result.current).toBe(false);
    await waitFor(() => expect(result.current).toBe(true));
  });

  it("stays unavailable while the status request is still in flight", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );

    const { result } = renderHook(() => useMetadataAvailable(), {
      wrapper: createQueryWrapper(),
    });

    await Promise.resolve();
    expect(result.current).toBe(false);
  });

  it("stays unavailable when the status request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("network down"))),
    );

    const { result } = renderHook(
      () => ({
        available: useMetadataAvailable(),
        query: useMetadataStatusQuery(),
      }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.query.isError).toBe(true));
    expect(result.current.available).toBe(false);
  });
});

describe("useTriggerMetadataUpdateMutation", () => {
  it("invalidates the status query on success, forcing an immediate refetch", async () => {
    const { fetchMock } = installMetadataApiMock({
      statusSequence: [
        {
          sources: [
            metadataSource({ name: "mictronics", status: "never-run" }),
          ],
        },
        {
          sources: [metadataSource({ name: "mictronics", status: "running" })],
        },
      ],
      triggerResult: {
        started: true,
        already_running: false,
        started_ms: 1_756_600_000_000,
      },
    });

    function useBoth() {
      return {
        query: useMetadataStatusQuery(),
        mutation: useTriggerMetadataUpdateMutation(),
      };
    }

    const { result } = renderHook(() => useBoth(), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() =>
      expect(result.current.query.data?.sources[0]?.status).toBe("never-run"),
    );

    result.current.mutation.mutate();

    await waitFor(() =>
      expect(result.current.query.data?.sources[0]?.status).toBe("running"),
    );
    const statusCalls = fetchMock.mock.calls.filter(
      ([url]) => url === "/api/internal/metadata/status",
    );
    expect(statusCalls.length).toBeGreaterThanOrEqual(2);
  });
});
