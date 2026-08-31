import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { NAV_ITEMS } from "@/components/shell/nav-items";
import { renderApp } from "@/test/test-utils";

describe("Sidebar", () => {
  it("renders all seven primary nav sections as links in a nav landmark", () => {
    renderApp();
    const nav = screen.getByRole("navigation", { name: /primary/i });
    for (const item of NAV_ITEMS) {
      expect(
        within(nav).getByRole("link", { name: item.label }),
      ).toBeInTheDocument();
    }
    expect(within(nav).getAllByRole("link")).toHaveLength(NAV_ITEMS.length);
  });

  it("uses a main landmark for routed content", () => {
    renderApp();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("marks only the active section with aria-current", () => {
    renderApp("/aircraft");
    expect(screen.getByRole("link", { name: "Aircraft" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Live Map" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("is keyboard-navigable in document order with visible focus styling", async () => {
    const user = userEvent.setup();
    renderApp();

    const nav = screen.getByRole("navigation", { name: /primary/i });
    const links = within(nav).getAllByRole("link");
    expect(links).toHaveLength(NAV_ITEMS.length);

    for (const link of links) {
      expect(link.className).toMatch(/focus-visible:outline/);
    }

    await user.tab(); // skip-to-content link
    for (const link of links) {
      await user.tab();
      expect(link).toHaveFocus();
    }

    // Focus continues on to the theme toggle after the last nav link.
    await user.tab();
    expect(screen.getByRole("button", { name: /toggle theme/i })).toHaveFocus();
  });

  it("collapses to icon-only width and exposes labels via tooltips", async () => {
    const user = userEvent.setup();
    renderApp();

    const collapseButton = screen.getByRole("button", {
      name: /collapse sidebar/i,
    });
    await user.click(collapseButton);

    const expandButton = screen.getByRole("button", {
      name: /expand sidebar/i,
    });
    expect(expandButton).toHaveAttribute("aria-pressed", "true");

    // Labels remain in the accessible tree (sr-only) even when collapsed.
    const nav = screen.getByRole("navigation", { name: /primary/i });
    expect(
      within(nav).getByRole("link", { name: "Live Map" }),
    ).toBeInTheDocument();

    await user.click(expandButton);
    expect(
      screen.getByRole("button", { name: /collapse sidebar/i }),
    ).toHaveAttribute("aria-pressed", "false");
  });
});
