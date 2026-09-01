import { afterEach, describe, expect, it } from "vitest";

import { resolveChartTheme } from "@/features/analytics/lib/chartTheme";

afterEach(() => {
  document.documentElement.removeAttribute("style");
});

describe("resolveChartTheme", () => {
  it("falls back to a plausible default when no CSS custom properties are set", () => {
    const theme = resolveChartTheme("dark");
    expect(theme.mode).toBe("dark");
    expect(theme.ink).toBeTruthy();
    expect(theme.mutedInk).toBeTruthy();
    expect(theme.grid).toBeTruthy();
    expect(theme.series).toHaveLength(3);
  });

  it("reads live CSS custom properties when set", () => {
    document.documentElement.style.setProperty("--foreground", "rgb(1, 2, 3)");
    document.documentElement.style.setProperty(
      "--muted-foreground",
      "rgb(4, 5, 6)",
    );
    document.documentElement.style.setProperty("--border", "rgb(7, 8, 9)");
    document.documentElement.style.setProperty(
      "--chart-series-1",
      "rgb(10, 11, 12)",
    );

    const theme = resolveChartTheme("light");

    expect(theme.ink).toBe("rgb(1, 2, 3)");
    expect(theme.mutedInk).toBe("rgb(4, 5, 6)");
    expect(theme.grid).toBe("rgb(7, 8, 9)");
    expect(theme.series[0]).toBe("rgb(10, 11, 12)");
  });

  it("returns different fallback colors for light and dark modes", () => {
    const light = resolveChartTheme("light");
    const dark = resolveChartTheme("dark");
    expect(light.ink).not.toBe(dark.ink);
    expect(light.series).not.toEqual(dark.series);
  });
});
