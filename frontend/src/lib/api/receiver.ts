/**
 * `GET /api/v1/receiver` (`docs/API.md` §3.2) as a TanStack Query hook.
 *
 * The live store already carries a `ReceiverInfo` snapshot, but only once
 * the WebSocket has connected — and only `features/map/aircraft/AircraftLayer`
 * opens that connection, so routes outside the Live Map (the Aircraft page
 * and its detail route, roadmap slice 029) never populate it. Those routes
 * still need `units` and `timezone` to format distances, altitudes and
 * timestamps, so they fetch the same block directly instead.
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
