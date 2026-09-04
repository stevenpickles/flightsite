/**
 * `GET /api/v1/receiver` (`docs/API.md` §3.2) as a TanStack Query hook.
 *
 * The live store already carries a `ReceiverInfo` snapshot, but only once the
 * WebSocket has *delivered a snapshot*. Since ADR-0015 the socket is opened by
 * `components/shell/AppShell` on every route rather than by the Live Map, so
 * that value now arrives everywhere — but it still arrives a connection and a
 * frame late, and it is absent for as long as the socket is down. Routes that
 * need `units` and `timezone` to format distances, altitudes and timestamps
 * (the Aircraft page and its detail route, roadmap slice 029) therefore keep
 * fetching the same block directly, and the store keeps the last one it saw
 * across an outage rather than dropping it with the picture.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { ReceiverInfo } from "@/lib/api/live";

const RECEIVER_PATH = "/api/v1/receiver";

export function getReceiver(): Promise<ReceiverInfo> {
  return fetch(RECEIVER_PATH).then(async (response) => {
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    return (await response.json()) as ReceiverInfo;
  });
}

/** Long `staleTime`: receiver identity/units/timezone change only through
 * the setup wizard or Settings, never on a cadence worth polling for. */
export function useReceiverQuery(): UseQueryResult<ReceiverInfo> {
  return useQuery({
    queryKey: ["receiver"],
    queryFn: getReceiver,
    staleTime: 5 * 60 * 1000,
  });
}
