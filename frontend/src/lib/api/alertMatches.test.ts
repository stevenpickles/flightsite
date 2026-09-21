/**
 * `useAlertMatchesQuery`'s refresh policy — docs/API.md §3.10, review R4-05.
 *
 * Against a real clock and a very short interval, because what is under test
 * is whether the option reaches `useQuery` at all and whether a second
 * answer actually reaches the consumer. The *interval the Alerts page
 * chooses*, and which pages it chooses it for, is a decision of
 * `AlertHistorySection` and is checked in that component's own test.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAlertMatchesQuery, type AlertMatch } from "@/lib/api/alertMatches";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A short enough interval that a real-time test stays fast, and long
 * enough that the first answer is on screen before the second is asked. */
const FAST_POLL_MS = 20;

function match(id: number, reason: string): AlertMatch {
  return {
    id,
    at: "2026-08-31T12:00:00.000Z",
    severity: "high",
    reason,
    icao: "ae1463",
    sighting_id: 42,
    callsign: null,
    registration: null,
    aircraft_type: null,
    closest_approach_nm: null,
    lowest_altitude_ft: null,
    rule: { id: 1, name: "Military aircraft" },
    builtin_key: null,
    notified: false,
  };
}

/** A history whose answer changes between identical requests, so a re-read
 * is visible in the data rather than only in a call count. */
function installChangingHistory() {
  let call = 0;
  const fetchMock = vi.fn(async () => {
    call += 1;
    return new Response(
      JSON.stringify({
        items: [match(call, `Rule: Answer ${call}`)],
        total: null,
        limit: 25,
        offset: 0,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** One client per test, created outside the wrapper component: building it
 * in the wrapper's body would hand every render a fresh cache and the hook
 * would never see its own second answer. */
function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      children,
    );
  };
}

describe("useAlertMatchesQuery", () => {
  it("re-reads on the interval it is given, and the new answer arrives", async () => {
    installChangingHistory();

    const { result } = renderHook(
      () =>
        useAlertMatchesQuery(
          { limit: 25, offset: 0 },
          { refetchInterval: FAST_POLL_MS },
        ),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });
    // Whatever answer arrived first, not a specific one: the interval is
    // short enough that pinning the *number* would be a race with the poll
    // rather than a statement about it.
    const first = result.current.data?.items[0]?.reason;

    await waitFor(() => {
      expect(result.current.data?.items[0]?.reason).not.toBe(first);
    });

    // Never a gap: the rows are replaced by the next answer, not cleared
    // while it is fetched.
    expect(result.current.data?.items).toHaveLength(1);
  });

  it("asks exactly once when it is given no interval", async () => {
    // The default has to be "no polling": most callers of this hook are
    // looking at a fixed window into the past, and a hook that polled
    // unless told not to would put every one of them on a timer.
    const fetchMock = installChangingHistory();

    const { result } = renderHook(
      () => useAlertMatchesQuery({ limit: 25, offset: 0 }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(result.current.data?.items[0]?.reason).toBe("Rule: Answer 1");
    });
    await new Promise((resolve) => setTimeout(resolve, FAST_POLL_MS * 20));

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
