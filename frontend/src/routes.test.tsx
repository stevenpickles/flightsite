import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { NAV_ITEMS, requireNavItem } from "@/components/shell/nav-items";
import { renderApp } from "@/test/test-utils";

describe("routing", () => {
  it("renders the Live Map (slice 013: a real map, no longer a placeholder) at the index route", () => {
    renderApp("/");
    const liveMap = requireNavItem("/");
    // The Live Map page's heading is visually hidden (the map is the
    // content) but stays in the a11y tree, so `getByRole` still finds it.
    expect(
      screen.getByRole("heading", { level: 1, name: liveMap.label }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("maplibre-container")).toBeInTheDocument();
  });

  it("switches to each section's page on navigation", async () => {
    const user = userEvent.setup();
    renderApp("/");

    for (const item of NAV_ITEMS) {
      if (item.to !== "/") {
        await user.click(screen.getByRole("link", { name: item.label }));
      }
      expect(
        screen.getByRole("heading", { level: 1, name: item.label }),
      ).toBeInTheDocument();
      // Every section except Live Map (slice 013) and Settings (slice 019)
      // is still a placeholder page. Settings renders its heading in every
      // `useConfigQuery` state (loading/error/loaded) but only shows this
      // description text once config has actually loaded — this sweep
      // deliberately runs without a config API mock, so Settings exercises
      // its no-fetch-mock (error) state here instead.
      if (item.to !== "/" && item.to !== "/settings") {
        expect(screen.getByText(item.description)).toBeInTheDocument();
      }
    }
  });

  it("renders the activity feed at /activity, outside the seven nav sections", () => {
    // Slice 035's standalone view. SPEC §10 fixes the primary navigation at
    // seven sections, so this route is deliberately absent from `NAV_ITEMS` —
    // the sweep above would otherwise demand a sidebar link for it — and is
    // reached from the Live Map panel's "View all" link instead, the same
    // shape as `/sightings/:id`.
    renderApp("/activity");

    expect(
      screen.getByRole("heading", { level: 1, name: "Activity" }),
    ).toBeInTheDocument();
    expect(NAV_ITEMS.some((item) => item.to === "/activity")).toBe(false);
  });
});
