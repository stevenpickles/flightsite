import { QueryClient } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { metadataStatusQueryKey } from "@/lib/api/metadata";
import {
  CLEAR_METADATA_CONFIRM_PHRASE,
  RESET_DATA_CONFIRM_PHRASE,
  useClearMetadataCacheMutation,
  useResetFlightSiteDataMutation,
} from "@/lib/api/reset";
import { createQueryWrapper } from "@/test/queryWrapper";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useClearMetadataCacheMutation", () => {
  it("POSTs the exact clear-metadata confirm phrase and returns the row counts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        cleared: true,
        aircraft_metadata_rows: 3,
        staging_rows: 0,
        resolved_rows: 3,
        classification_rows: 0,
        operator_rows: 1,
        operator_group_rows: 1,
        route_cache_rows: 2,
        airport_rows: 5,
        sources_reset: 1,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useClearMetadataCacheMutation(), {
      wrapper: createQueryWrapper(),
    });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/internal/reset/metadata-cache");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      confirm: CLEAR_METADATA_CONFIRM_PHRASE,
    });
    expect(result.current.data?.aircraft_metadata_rows).toBe(3);
    expect(result.current.data?.airport_rows).toBe(5);
  });

  it("invalidates the metadata status query on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          cleared: true,
          aircraft_metadata_rows: 0,
          staging_rows: 0,
          resolved_rows: 0,
          classification_rows: 0,
          operator_rows: 0,
          operator_group_rows: 0,
          route_cache_rows: 0,
          airport_rows: 0,
          sources_reset: 0,
        }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useClearMetadataCacheMutation(), {
      wrapper: createQueryWrapper(queryClient),
    });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: metadataStatusQueryKey,
    });
  });

  it("surfaces a 422 (wrong or absent confirm) as an error, without pretending success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail:
              "confirm must be exactly 'clear-metadata' to perform this action",
          },
          422,
        ),
      ),
    );

    const { result } = renderHook(() => useClearMetadataCacheMutation(), {
      wrapper: createQueryWrapper(),
    });
    result.current.mutate();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/clear-metadata/);
  });
});

describe("useResetFlightSiteDataMutation", () => {
  it("POSTs the exact reset-flightsite-data confirm phrase and returns the 202 envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          accepted: true,
          requested_ms: 1_756_600_000_000,
          restart_required: true,
          message: "FlightSite data will be reset on the next restart.",
        },
        202,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useResetFlightSiteDataMutation(), {
      wrapper: createQueryWrapper(),
    });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/internal/reset/data");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      confirm: RESET_DATA_CONFIRM_PHRASE,
    });
    expect(result.current.data?.restart_required).toBe(true);
  });
});
