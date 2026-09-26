/**
 * Confirms the `/receiver/feeders` route (roadmap slice 077) actually works
 * end to end through the real, lazily-loaded route definition in
 * `src/routes.tsx` — mirrors `ReceiverPage.lazyRoute.test.tsx` (roadmap
 * slice 034), which established the pattern for a route whose page pulls in
 * ECharts.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/lib/queryClient";
import { router } from "@/routes";
import { installFeedersApiMock } from "@/test/feedersApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Feeders lazy route", () => {
  it("loads the Feeders page through the router's lazy import", async () => {
    installFeedersApiMock();

    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await act(async () => {
      await router.navigate("/receiver/feeders");
    });

    // The dynamic import behind `React.lazy` genuinely fetches and evaluates
    // a module under Vitest's transform pipeline, so this can take longer
    // than the default poll window under load — give it more room, mirroring
    // `ReceiverPage.lazyRoute.test.tsx`.
    expect(
      await screen.findByRole(
        "heading",
        { level: 1, name: "Feeders" },
        { timeout: 10000 },
      ),
    ).toBeInTheDocument();
  }, 15000);
});
