import { QueryClient } from "@tanstack/react-query";

/**
 * Shared TanStack Query client. No queries are registered yet in this slice
 * (frontend skeleton) — real data fetching arrives with the API-integrated
 * feature slices. Defaults favor the live-data-first nature of the app:
 * short staleness, no refetch storms on window focus for placeholder pages.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
