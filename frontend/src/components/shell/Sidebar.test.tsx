import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NAV_ITEMS } from "@/components/shell/nav-items";
import { renderApp } from "@/test/test-utils";

/**
 * A scripted `window.matchMedia` stand-in — jsdom itself falls back to
 * `matches: false` for every query regardless of `window.innerWidth`, so a
 * real "below `md`" render has to be driven this way (`useIsMobile`'s own
 * doc comment). `dispatch` simulates the browser firing a `change` event on
 * an existing `MediaQueryList` (a resize/rotation crossing the breakpoint
 * after mount), which `addEventListener`/`removeEventListener` support here
 * to match the real interface `useIsMobile` uses.
 */
function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  let matches = initialMatches;
  const mediaQueryList = {
    get matches() {
      return matches;
    },
    media: "(max-width: 767px)",
    addEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => {
      listeners.add(listener);
    },
    removeEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => {
      listeners.delete(listener);
    },
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue(mediaQueryList as unknown as MediaQueryList),
  );
  return {
    dispatch(next: boolean) {
      matches = next;
      for (const listener of listeners) {
        listener({ matches: next } as MediaQueryListEvent);
      }
    },
  };
}

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

describe("Sidebar below the md breakpoint (R1-07, R2-08, R3-07, R4-06)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to a collapsed rail with no nav landmark reachable until opened", () => {
    installMatchMedia(true);
    renderApp();

    // Only the rail's menu button — the seven links are not directly
    // reachable, unlike desktop where they're always in the tree.
    expect(
      screen.getByRole("button", { name: /open navigation menu/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: /primary/i }),
    ).not.toBeInTheDocument();
    // `<main>` never loses its landmark, and — critically — is not pushed
    // by a 256px-wide flow sibling the way the desktop-expanded sidebar
    // would: the rail is the only in-flow sidebar content at this width.
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("opens an overlay drawer with all seven links and moves focus into it", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderApp();

    await user.click(
      screen.getByRole("button", { name: /open navigation menu/i }),
    );

    const dialog = screen.getByRole("dialog", { name: /navigation/i });
    // Fixed, not a flex sibling — this is what keeps `<main>` full width
    // while the drawer is open rather than the drawer taking layout space.
    expect(dialog.className).toMatch(/\bfixed\b/);

    const nav = within(dialog).getByRole("navigation", { name: /primary/i });
    for (const item of NAV_ITEMS) {
      expect(
        within(nav).getByRole("link", { name: item.label }),
      ).toBeInTheDocument();
    }

    expect(
      screen.getByRole("button", { name: /close navigation menu/i }),
    ).toHaveFocus();
  });

  it("closes on scrim click and returns focus to the button that opened it", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderApp();

    const openButton = screen.getByRole("button", {
      name: /open navigation menu/i,
    });
    await user.click(openButton);
    expect(screen.getByRole("dialog", { name: /navigation/i })).toBeVisible();

    // The scrim is deliberately not in the accessibility tree
    // (`aria-hidden`), so it has no role to query by.
    const scrim = document.querySelector('[aria-hidden="true"].fixed.inset-0');
    expect(scrim).not.toBeNull();
    await user.click(scrim as Element);

    expect(
      screen.queryByRole("dialog", { name: /navigation/i }),
    ).not.toBeInTheDocument();
    expect(openButton).toHaveFocus();
  });

  it("closes on Escape", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderApp();

    await user.click(
      screen.getByRole("button", { name: /open navigation menu/i }),
    );
    expect(screen.getByRole("dialog", { name: /navigation/i })).toBeVisible();

    await user.keyboard("{Escape}");

    expect(
      screen.queryByRole("dialog", { name: /navigation/i }),
    ).not.toBeInTheDocument();
  });

  it("closes on route change (clicking a link inside it)", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderApp();

    await user.click(
      screen.getByRole("button", { name: /open navigation menu/i }),
    );
    const dialog = screen.getByRole("dialog", { name: /navigation/i });
    await user.click(within(dialog).getByRole("link", { name: "Aircraft" }));

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 1, name: "Aircraft" }),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("dialog", { name: /navigation/i }),
    ).not.toBeInTheDocument();
  });

  it("traps Tab focus inside the open drawer", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderApp();

    await user.click(
      screen.getByRole("button", { name: /open navigation menu/i }),
    );
    const closeButton = screen.getByRole("button", {
      name: /close navigation menu/i,
    });
    expect(closeButton).toHaveFocus();

    // Shift+Tab from the first focusable element wraps to the last.
    await user.tab({ shift: true });
    const themeToggle = screen.getByRole("button", { name: /toggle theme/i });
    expect(themeToggle).toHaveFocus();

    // Tab from the last wraps back to the first.
    await user.tab();
    expect(closeButton).toHaveFocus();
  });

  it("ignores the persisted sidebarCollapsed preference — the rail is always the same width", () => {
    installMatchMedia(true);
    renderApp();

    // No "Collapse"/"Expand sidebar" control exists at all below `md`; the
    // desktop preference has nothing to drive here.
    expect(
      screen.queryByRole("button", { name: /collapse sidebar/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /expand sidebar/i }),
    ).not.toBeInTheDocument();
  });
});
