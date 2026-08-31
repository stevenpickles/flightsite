import { beforeEach, describe, expect, it, vi } from "vitest";

const STORAGE_KEY = "flightsite-ui-theme";

describe("useUiStore", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
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

  it("falls back to dark for a corrupted stored value", async () => {
    window.localStorage.setItem(STORAGE_KEY, "not-a-theme");
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().theme).toBe("dark");
  });

  it("toggleTheme flips the theme, persists it, and updates the html class", async () => {
    const { useUiStore } = await import("./useUiStore");

    useUiStore.getState().toggleTheme();
    expect(useUiStore.getState().theme).toBe("light");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");

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

  it("sidebar starts expanded; toggleSidebar and setSidebarCollapsed flip it", async () => {
    const { useUiStore } = await import("./useUiStore");
    expect(useUiStore.getState().sidebarCollapsed).toBe(false);

    useUiStore.getState().toggleSidebar();
    expect(useUiStore.getState().sidebarCollapsed).toBe(true);

    useUiStore.getState().setSidebarCollapsed(false);
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

    window.localStorage.getItem = originalGetItem;
    window.localStorage.setItem = originalSetItem;
  });
});
