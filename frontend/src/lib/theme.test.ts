import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyThemeClass,
  readStoredTheme,
  readSystemPrefersDark,
  resolveTheme,
  THEME_STORAGE_KEY,
  watchSystemPrefersDark,
  writeStoredTheme,
} from "./theme";

describe("theme helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("readStoredTheme defaults to dark when nothing is stored", () => {
    expect(readStoredTheme()).toBe("dark");
  });

  it("readStoredTheme returns a validly stored theme", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(readStoredTheme()).toBe("light");
  });

  it("readStoredTheme accepts a stored system preference", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    expect(readStoredTheme()).toBe("system");
  });

  it("readStoredTheme rejects invalid stored values", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readStoredTheme()).toBe("dark");
  });

  it("writeStoredTheme persists the value for later reads", () => {
    writeStoredTheme("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(readStoredTheme()).toBe("light");
  });

  it("applyThemeClass toggles the dark class and color-scheme", () => {
    applyThemeClass("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");

    applyThemeClass("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");
  });

  it("resolveTheme passes dark/light through unchanged", () => {
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it("resolveTheme defers to the system reading for 'system'", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("readSystemPrefersDark falls back to true with no matchMedia", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(readSystemPrefersDark()).toBe(true);
  });

  it("readSystemPrefersDark reads the live OS preference", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: true } as MediaQueryList),
    );
    expect(readSystemPrefersDark()).toBe(true);
  });

  it("watchSystemPrefersDark calls back on a live OS preference change", () => {
    const listeners = new Set<(event: MediaQueryListEvent) => void>();
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({
        matches: false,
        addEventListener: (
          _type: string,
          listener: (event: MediaQueryListEvent) => void,
        ) => listeners.add(listener),
        removeEventListener: (
          _type: string,
          listener: (event: MediaQueryListEvent) => void,
        ) => listeners.delete(listener),
      } as unknown as MediaQueryList),
    );

    const onChange = vi.fn();
    const unsubscribe = watchSystemPrefersDark(onChange);
    for (const listener of listeners) {
      listener({ matches: true } as MediaQueryListEvent);
    }
    expect(onChange).toHaveBeenCalledWith(true);

    unsubscribe();
    expect(listeners.size).toBe(0);
  });

  it("watchSystemPrefersDark is a no-op subscription with no matchMedia", () => {
    vi.stubGlobal("matchMedia", undefined);
    const onChange = vi.fn();
    expect(() => watchSystemPrefersDark(onChange)()).not.toThrow();
    expect(onChange).not.toHaveBeenCalled();
  });
});
