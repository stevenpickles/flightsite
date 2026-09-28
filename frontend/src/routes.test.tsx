import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { NAV_ITEMS, requireNavItem } from "@/components/shell/nav-items";
import { renderApp } from "@/test/test-utils";

const OWN_HEADER_SECTIONS = new Set([
  "/activity",
  "/health",
  "/receiver/feeders",
]);

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
      // its no-fetch-mock (error) state here instead. Activity, Health and
      // Feeders (primary since the SPEC §10 amendment of 2026-09-28) have
      // their own page headers and never rendered the nav description.
      if (
        item.to !== "/" &&
        item.to !== "/settings" &&
        !OWN_HEADER_SECTIONS.has(item.to)
      ) {
        expect(screen.getByText(item.description)).toBeInTheDocument();
      }
    }
  });

  it("puts Activity, Health and Feeders in the primary navigation", () => {
    // SPEC §10 amendment of 2026-09-28 (slice 082): the three pages that were
    // reachable only through in-page links are primary sections too.
    for (const path of ["/activity", "/health", "/receiver/feeders"]) {
      expect(NAV_ITEMS.some((item) => item.to === path)).toBe(true);
    }
  });

  it("renders the activity feed at /activity", () => {
    renderApp("/activity");

    expect(
      screen.getByRole("heading", { level: 1, name: "Activity" }),
    ).toBeInTheDocument();
  });

  it("renders NotFoundPage inside the shell for a path matching no route (R0-02, R2-16)", () => {
    renderApp("/nope-not-a-route");

    // Inside the shell, not React Router's raw developer screen: the
    // sidebar is still there.
    expect(
      screen.getByRole("navigation", { name: /primary/i }),
    ).toBeInTheDocument();

    const main = screen.getByRole("main");
    expect(
      within(main).getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
    expect(within(main).getByText("/nope-not-a-route")).toBeInTheDocument();

    // Lists every primary section as a way back, not just the Live Map.
    for (const item of NAV_ITEMS) {
      expect(
        within(main).getByRole("link", { name: item.label }),
      ).toBeInTheDocument();
    }
  });
});
