import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type PropsWithChildren } from "react";

/** A `renderHook` wrapper providing a `QueryClientProvider`, for tests that
 * exercise a TanStack Query hook directly rather than through a rendered
 * component tree. Reuses `queryClient` when given one, so a test can share
 * a single cache across multiple `renderHook` calls (e.g. asserting a
 * mutation updates what a query already has cached). */
export function createQueryWrapper(queryClient?: QueryClient) {
  const client =
    queryClient ??
    new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function QueryWrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client }, children);
  };
}
