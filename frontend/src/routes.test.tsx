import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { NAV_ITEMS, requireNavItem } from "@/components/shell/nav-items";
import { renderApp } from "@/test/test-utils";

describe("routing", () => {
  it("renders the Live Map placeholder at the index route", () => {
    renderApp("/");
    const liveMap = requireNavItem("/");
    expect(
      screen.getByRole("heading", { level: 1, name: liveMap.label }),
    ).toBeInTheDocument();
    expect(screen.getByText(liveMap.description)).toBeInTheDocument();
  });

  it("switches to each section's placeholder page on navigation", async () => {
    const user = userEvent.setup();
    renderApp("/");

    for (const item of NAV_ITEMS) {
      if (item.to !== "/") {
        await user.click(screen.getByRole("link", { name: item.label }));
      }
      expect(
        screen.getByRole("heading", { level: 1, name: item.label }),
      ).toBeInTheDocument();
      expect(screen.getByText(item.description)).toBeInTheDocument();
    }
  });
});
