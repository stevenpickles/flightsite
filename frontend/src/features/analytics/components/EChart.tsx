/**
 * The shared chart wrapper every Analytics card renders through (roadmap
 * slice 032). Owns everything a raw ECharts instance needs that a React
 * component should not repeat per card:
 *
 * - **Theme-aware**: rebuilds the option from {@link ChartTheme} whenever the
 *   app theme toggles, via `buildOption` — a pure function of the theme
 *   rather than a static object, so a card never hand-rolls its own
 *   light/dark branching.
 * - **Resize-observing**: keeps the chart sized to its container (the card
 *   grid is responsive) without a page-level resize listener.
 * - **Disposes on unmount**: an ECharts instance holds a canvas and internal
 *   render state that a card unmounting (preset switch, navigation away)
 *   must not leak.
 * - **Accessible**: `role="img"` plus `aria-label` names the chart for
 *   assistive tech that announces the container, and a visually-hidden
 *   `summary` paragraph is the real text alternative (`docs/TEST_STRATEGY.md`
 *   §2's chart-a11y expectation) — a screen reader user gets the data, not
 *   just a label saying a chart exists.
 * - **Empty state**: `buildOption` returning `null` (no rows in the window)
 *   renders "No data" instead of an empty canvas.
 *
 * ECharts itself is registered modularly by `lib/echartsSetup` (imported
 * here for its side effect) rather than pulled in whole — see that module's
 * comment.
 */
import "@/features/analytics/lib/echartsSetup";

import * as echarts from "echarts/core";
import { useEffect, useMemo, useRef } from "react";

import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { resolveChartTheme } from "@/features/analytics/lib/chartTheme";
import { useUiStore } from "@/store/useUiStore";

export interface EChartClickParams {
  /** The clicked mark's `dataIndex`/`name`/`value` etc. — echarts' own
   * `ECElementEvent`, kept loose here so callers narrow what they need. */
  dataIndex: number;
  name: string;
  value: unknown;
}

export interface EChartProps {
  /** Builds the option from the resolved theme. Returning `null` renders the
   * empty state instead of an (empty) chart — the card's call, based on
   * whether its query actually has rows to plot. */
  buildOption: (theme: ChartTheme) => echarts.EChartsCoreOption | null;
  /** Announces what the chart shows to assistive tech (`role="img"`'s
   * label) — e.g. `"Top aircraft by sightings, bar chart"`. */
  ariaLabel: string;
  /** The visually-hidden text alternative: a plain-language description of
   * the data the chart renders (not just its title), so a screen reader
   * user gets the figures. */
  summary: string;
  /** Fixed pixel height; the chart always fills its container's width. */
  height?: number;
  className?: string;
  /** Fired on a mark click (e.g. a top-aircraft bar), for row-level
   * navigation. */
  onMarkClick?: (params: EChartClickParams) => void;
}

const DEFAULT_HEIGHT = 280;

export function EChart({
  buildOption,
  ariaLabel,
  summary,
  height = DEFAULT_HEIGHT,
  className,
  onMarkClick,
}: EChartProps) {
  const theme = useUiStore((state) => state.theme);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const onMarkClickRef = useRef(onMarkClick);
  useEffect(() => {
    onMarkClickRef.current = onMarkClick;
  }, [onMarkClick]);

  const option = useMemo(
    () => buildOption(resolveChartTheme(theme)),
    [buildOption, theme],
  );
  const isEmpty = option === null;

  // Mounts (and disposes) the ECharts instance itself, exactly once per
  // container mount — a chart transitioning to/from the empty state
  // unmounts/remounts the container div, which this depends on.
  useEffect(() => {
    const el = containerRef.current;
    if (el === null) {
      return;
    }
    const instance = echarts.init(el);
    chartRef.current = instance;

    instance.on("click", (params: unknown) => {
      const clicked = params as EChartClickParams;
      onMarkClickRef.current?.(clicked);
    });

    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => instance.resize())
        : null;
    resizeObserver?.observe(el);

    return () => {
      resizeObserver?.disconnect();
      instance.dispose();
      chartRef.current = null;
    };
    // `isEmpty` is the real dependency (it decides whether the container
    // exists) — `buildOption`/`theme` changes are handled by the setOption
    // effect below without tearing the instance down.
  }, [isEmpty]);

  // Applies a freshly-built (possibly re-themed) option to the live
  // instance, without re-creating it — this is what makes a theme toggle
  // "rebuild options" rather than flicker the whole chart.
  useEffect(() => {
    if (chartRef.current !== null && option !== null) {
      chartRef.current.setOption(option, true);
    }
  }, [option]);

  if (isEmpty) {
    return (
      <div className={className} style={{ minHeight: height }}>
        <p
          role="status"
          className="flex h-full min-h-[inherit] items-center justify-center text-sm text-muted-foreground"
        >
          No data for this window.
        </p>
      </div>
    );
  }

  return (
    <div className={className}>
      <div
        ref={containerRef}
        role="img"
        aria-label={ariaLabel}
        style={{ height, width: "100%" }}
      />
      <p className="sr-only">{summary}</p>
    </div>
  );
}
