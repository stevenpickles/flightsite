import { beforeEach, describe, expect, it } from "vitest";

import {
  applyThemeClass,
  readStoredTheme,
  THEME_STORAGE_KEY,
  writeStoredTheme,
} from "./theme";

describe("theme helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
  });

  it("readStoredTheme defaults to dark when nothing is stored", () => {
    expect(readStoredTheme()).toBe("dark");
  });

  it("readStoredTheme returns a validly stored theme", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(readStoredTheme()).toBe("light");
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
});
