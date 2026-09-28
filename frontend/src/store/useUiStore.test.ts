import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const STORAGE_KEY = "flightsite-ui-theme";
const SIDEBAR_STORAGE_KEY = "flightsite-sidebar-collapsed";

/** A scripted `matchMedia` stand-in, mirroring `Sidebar.test.tsx`'s own —
 * real jsdom always reports `matches: false`, so a "system prefers dark"
 * case needs this to exist at all. */
function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  let matches = initialMatches;
  const mediaQueryList = {
    get matches() {
      return matches;
    },
    media: "(prefers-color-scheme: dark)",
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

describe("useUiStore", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to the dark theme when nothing is stored", async () => {
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().theme).toBe("dark");
  });

  it("initializes from a previously persisted theme", async () => {
    window.localStorage.setItem(STORAGE_KEY, "light");
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().theme).toBe("light");
  });

  it("initializes from a previously persisted system preference", async () => {
    window.localStorage.setItem(STORAGE_KEY, "system");
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().theme).toBe("system");
  });

  it("falls back to dark for a corrupted stored value", async () => {
    window.localStorage.setItem(STORAGE_KEY, "not-a-theme");
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().theme).toBe("dark");
  });

  it("toggleTheme cycles Dark -> Light -> System -> Dark, persisting and applying each step", async () => {
    const { useUiStore } = await import("./useUiStore");

    useUiStore.getState().toggleTheme();
    expect(useUiStore.getState().theme).toBe("light");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");

    useUiStore.getState().toggleTheme();
    expect(useUiStore.getState().theme).toBe("system");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("system");

    useUiStore.getState().toggleTheme();
    expect(useUiStore.getState().theme).toBe("dark");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("setTheme sets an explicit theme", async () => {
    const { useUiStore } = await import("./useUiStore");
    useUiStore.getState().setTheme("light");
    expect(useUiStore.getState().theme).toBe("light");
    useUiStore.getState().setTheme("dark");
    expect(useUiStore.getState().theme).toBe("dark");
  });

  it("useResolvedTheme resolves 'system' against the live OS preference", async () => {
    installMatchMedia(true);
    const { useUiStore } = await import("./useUiStore");
    useUiStore.getState().setTheme("system");
    expect(useUiStore.getState().systemPrefersDark).toBe(true);

    // resolveTheme is exercised directly through the store's own fields —
    // see `theme.test.ts` for the pure-function contract.
    const { resolveTheme } = await import("@/lib/theme");
    const state = useUiStore.getState();
    expect(resolveTheme(state.theme, state.systemPrefersDark)).toBe("dark");
  });

  it("follows a live OS theme change while set to System, with no reload", async () => {
    const media = installMatchMedia(false);
    const { useUiStore } = await import("./useUiStore");
    useUiStore.getState().setTheme("system");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    media.dispatch(true);
    expect(useUiStore.getState().systemPrefersDark).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("never overrides an explicit Dark/Light choice on an OS change", async () => {
    const media = installMatchMedia(false);
    const { useUiStore } = await import("./useUiStore");
    useUiStore.getState().setTheme("light");

    media.dispatch(true);
    // The reading is still tracked for later...
    expect(useUiStore.getState().systemPrefersDark).toBe(true);
    // ...but an explicit Light choice never gets silently overridden.
    expect(useUiStore.getState().theme).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("sidebar starts expanded; toggleSidebar and setSidebarCollapsed flip it", async () => {
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().sidebarCollapsed).toBe(false);

    useUiStore.getState().toggleSidebar();
    expect(useUiStore.getState().sidebarCollapsed).toBe(true);

    useUiStore.getState().setSidebarCollapsed(false);
    expect(useUiStore.getState().sidebarCollapsed).toBe(false);
  });

  it("persists the sidebar collapse choice across a simulated reload", async () => {
    const first = await import("./useUiStore");
    first.useUiStore.getState().setSidebarCollapsed(true);
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");

    vi.resetModules();
    const second = await import("./useUiStore");
    expect(second.useUiStore.getState().sidebarCollapsed).toBe(true);
  });

  it("falls back to expanded for a corrupted stored sidebar value", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "not-a-boolean");
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().sidebarCollapsed).toBe(false);
  });

  it("keeps the in-memory theme usable even when storage read/write throw", async () => {
    const originalGetItem = window.localStorage.getItem.bind(
      window.localStorage,
    );
    const originalSetItem = window.localStorage.setItem.bind(
      window.localStorage,
    );
    window.localStorage.getItem = () => {
      throw new Error("storage disabled");
    };
    window.localStorage.setItem = () => {
      throw new Error("storage disabled");
    };

    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().theme).toBe("dark");

    expect(() => {
      useUiStore.getState().toggleTheme();
    }).not.toThrow();
    expect(useUiStore.getState().theme).toBe("light");

    expect(() => {
      useUiStore.getState().toggleSidebar();
    }).not.toThrow();
    expect(useUiStore.getState().sidebarCollapsed).toBe(true);

    window.localStorage.getItem = originalGetItem;
    window.localStorage.setItem = originalSetItem;
  });
});
