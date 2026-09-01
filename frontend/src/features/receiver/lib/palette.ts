/**
 * Chart color tokens for the Receiver page (roadmap slice 034), and the hook
 * that tracks which mode is active.
 *
 * `frontend/src/lib/theme.ts` toggles a `.dark` class on `<html>` rather than
 * relying on `prefers-color-scheme` alone, and ECharts draws to a `<canvas>`
 * rather than the DOM — its colors cannot be expressed as CSS custom
 * properties that repaint themselves, so each series/axis color is resolved
 * to a concrete hex value per mode here and re-applied whenever the class
 * flips (`useIsDarkTheme`).
 *
 * Values are the validated default categorical/status palette (Claude
 * skill `dataviz`, `references/palette.md`): slot 1 (blue) and slot 2
 * (orange) as the two-series pair used wherever a chart overlays two series
 * (e.g. "today" vs "ever" range-by-bearing) — chosen for the CVD/normal-vision
 * separation the reference palette validates for an *adjacent* pair, not
 * picked ad hoc. Chart chrome (ink, gridlines, axis) is that same palette's
 * "Chart chrome & ink" table.
 */
import { useEffect, useState } from "react";

export interface ReceiverChartPalette {
  /** Categorical slot 1 (blue) — the primary series in a single-series chart,
   * and the "current/ever" side of a two-series overlay. */
  series1: string;
  /** Categorical slot 2 (orange) — the second series of a two-series overlay
   * (e.g. "today" range-by-bearing over "ever"). */
  series2: string;
  surface: string;
  primaryInk: string;
  secondaryInk: string;
  mutedInk: string;
  gridline: string;
  axisLine: string;
}

const LIGHT_PALETTE: ReceiverChartPalette = {
  series1: "#2a78d6",
  series2: "#eb6834",
  surface: "#fcfcfb",
  primaryInk: "#0b0b0b",
  secondaryInk: "#52514e",
  mutedInk: "#898781",
  gridline: "#e1e0d9",
  axisLine: "#c3c2b7",
};

const DARK_PALETTE: ReceiverChartPalette = {
  series1: "#3987e5",
  series2: "#d95926",
  surface: "#1a1a19",
  primaryInk: "#ffffff",
  secondaryInk: "#c3c2b7",
  mutedInk: "#898781",
  gridline: "#2c2c2a",
  axisLine: "#383835",
};

export function chartPalette(isDark: boolean): ReceiverChartPalette {
  return isDark ? DARK_PALETTE : LIGHT_PALETTE;
}

function isDarkNow(): boolean {
  if (typeof document === "undefined") {
    return false;
  }
  return document.documentElement.classList.contains("dark");
}

/** Tracks `<html>`'s `.dark` class (`applyThemeClass`, `lib/theme.ts`) so a
 * chart can re-derive its colors when the user flips the theme toggle. */
export function useIsDarkTheme(): boolean {
  const [isDark, setIsDark] = useState(isDarkNow);

  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => setIsDark(isDarkNow()));
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return isDark;
}
