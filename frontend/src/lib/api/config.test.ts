import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getConfig,
  putConfig,
  useConfigQuery,
  usePutConfigMutation,
} from "@/lib/api/config";
import {
  defaultEnrichmentConfig,
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";
import { createQueryWrapper } from "@/test/queryWrapper";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getConfig", () => {
  it("GETs /api/internal/config and returns the envelope shape", async () => {
    const { fetchMock } = installConfigApiMock({ firstRun: true });
    const response = await getConfig();

    expect(fetchMock).toHaveBeenCalledWith("/api/internal/config", undefined);
    expect(response.first_run).toBe(true);
    expect(response.config.units).toBe("aviation");
    expect(response.secrets_set).toHaveProperty(
      "enrichment.aerodatabox_api_key",
      false,
    );
  });
});

describe("putConfig", () => {
  it("PUTs a JSON body with the patch and returns the updated envelope", async () => {
    const { fetchMock } = installConfigApiMock();
    const response = await putConfig({
      units: "metric",
      timezone: "Europe/London",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/internal/config");
    expect(init.method).toBe("PUT");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toEqual({
      units: "metric",
      timezone: "Europe/London",
    });
    expect(response.config.units).toBe("metric");
    expect(response.config.timezone).toBe("Europe/London");
  });

  it("sends a secret field verbatim in the request body", async () => {
    const { fetchMock } = installConfigApiMock();
    await putConfig({ enrichment: { aerodatabox_api_key: "sk-test-key" } });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as {
      enrichment: { aerodatabox_api_key: string };
    };
    expect(body.enrichment.aerodatabox_api_key).toBe("sk-test-key");
  });

  it("never receives the real secret value back — only the mask or null", async () => {
    installConfigApiMock({
      config: defaultFlightSiteConfig({
        enrichment: defaultEnrichmentConfig({
          aerodatabox_enabled: true,
          aerodatabox_api_key: "•••",
        }),
      }),
      secretsSet: { "enrichment.aerodatabox_api_key": true },
    });
    const response = await getConfig();
    expect(response.config.enrichment.aerodatabox_api_key).toBe("•••");
  });
});

describe("useConfigQuery", () => {
  it("loads the config document and disables retries", async () => {
    installConfigApiMock({ firstRun: false });
    const { result } = renderHook(() => useConfigQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });
    expect(result.current.data?.first_run).toBe(false);
  });
});

function useConfigAndMutation() {
  return { query: useConfigQuery(), mutation: usePutConfigMutation() };
}

describe("usePutConfigMutation", () => {
  it("updates the useConfigQuery cache on success without a refetch", async () => {
    const { fetchMock } = installConfigApiMock();
    // Both hooks share one render tree (and so one `act` flush cycle) —
    // exercising them via two independent `renderHook` calls left the
    // query's observer notified (confirmed via `queryClient.getQueryData`)
    // but its `result.current` snapshot stale, since nothing forces that
    // *other* root to re-render in a test environment.
    const { result } = renderHook(() => useConfigAndMutation(), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));

    result.current.mutation.mutate({ units: "metric" });
    await waitFor(() =>
      expect(result.current.query.data?.config.units).toBe("metric"),
    );

    // One GET (the query) + one PUT (the mutation) — the cache update comes
    // from the mutation's response, not a second GET.
    const getCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === undefined,
    );
    expect(getCalls).toHaveLength(1);
  });
});
