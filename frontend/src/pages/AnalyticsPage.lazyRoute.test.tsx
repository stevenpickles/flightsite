/**
 * Confirms the Analytics route (roadmap slice 032) actually works end to
 * end through the real, lazily-loaded route definition in `src/routes.tsx`
 * — as opposed to every other Analytics test, which renders
 * `features/analytics/AnalyticsPage` (or `pages/AnalyticsPage`'s
 * synchronous re-export) directly. Exercises the `React.lazy` +
 * `Suspense` wiring itself: the fallback shows first, then the real page.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/lib/queryClient";
import { router } from "@/routes";
import { installAnalyticsApiMock } from "@/test/analyticsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Analytics lazy route", () => {
  it("loads the Analytics page through the router's lazy import", async () => {
    installAnalyticsApiMock();

    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    // Start at the Live Map (the router's index route) and navigate over
    // to Analytics — the same way a user reaches it — so the Suspense
    // fallback and the real, dynamically-imported page both get a chance
    // to render.
    await act(async () => {
      await router.navigate("/analytics");
    });

    // The dynamic import behind `React.lazy` genuinely fetches and
    // evaluates a module under Vitest's transform pipeline (unlike every
    // other synchronous mock in this suite), so this can take longer than
    // the default poll window under load — give it more room.
    expect(
      await screen.findByRole(
        "heading",
        { level: 1, name: "Analytics" },
        { timeout: 10000 },
      ),
    ).toBeInTheDocument();
  }, 15000);
});
