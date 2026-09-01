import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getMetadataStatus,
  triggerMetadataUpdate,
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
