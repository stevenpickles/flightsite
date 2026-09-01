/**
 * Resolves the app's design tokens into the colors an ECharts option needs
 * (`EChart.tsx` calls this on every render, so a theme toggle always rebuilds
 * with fresh colors — roadmap slice 032).
 *
 * Reads the live CSS custom properties `index.css` defines on `:root`/`.dark`
 * — `--foreground`, `--muted-foreground`, `--border` for ink/grid, and the
 * three fixed categorical `--chart-series-*` hues (data-viz method: fixed
 * hue order, never cycled; the first slot doubles as the single-hue color
 * for a one-series chart) — so a chart always matches the app's live theme
 * rather than a value baked in at build time. Falls back to a value drawn
 * from the same tokens when a property is unset (jsdom under test, or a
 * runtime that has not applied `index.css` yet), so the resolver never
 * fails — it degrades to a plausible default instead.
 */

import type { Theme } from "@/lib/theme";

export interface ChartTheme {
  mode: Theme;
  /** Primary text/axis-label ink (`--foreground`). */
  ink: string;
  /** Secondary ink for axis ticks and captions (`--muted-foreground`). */
  mutedInk: string;
  /** Recessive gridline/axis-line color (`--border`). */
  grid: string;
  /** Three fixed categorical hues, in order — never reassigned by data. */
  series: readonly [string, string, string];
}

const FALLBACK: Record<Theme, ChartTheme> = {
  light: {
    mode: "light",
    ink: "#20242d",
    mutedInk: "#6b7280",
    grid: "#dfe1e6",
    // Kept in lockstep with `--chart-series-*` in index.css; series 3 was
    // darkened in slice 048 to clear the 3:1 contrast floor on the light card.
    series: ["#2a78d6", "#eb6834", "#149463"],
  },
  dark: {
    mode: "dark",
    ink: "#e8ecf1",
    mutedInk: "#9aa3ad",
    grid: "#33394a",
    series: ["#3987e5", "#d95926", "#199e70"],
  },
};

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return fallback;
  }
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value.length > 0 ? value : fallback;
}

/** Resolves the current chart theme for `mode`. The categorical hue *order*
 * is the CVD-safety mechanism (data-viz method) and never changes, but each
 * slot's exact step is still read live so it stays in sync with a token
 * edit in `index.css` without a code change here. */
export function resolveChartTheme(mode: Theme): ChartTheme {
  const base = FALLBACK[mode];
  return {
    mode,
    ink: cssVar("--foreground", base.ink),
    mutedInk: cssVar("--muted-foreground", base.mutedInk),
    grid: cssVar("--border", base.grid),
    series: [
      cssVar("--chart-series-1", base.series[0]),
      cssVar("--chart-series-2", base.series[1]),
      cssVar("--chart-series-3", base.series[2]),
    ],
  };
}
