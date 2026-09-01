/**
 * Minimal ECharts wrapper for the Receiver page (roadmap slice 034).
 *
 * DEVIATION FOR REVIEWER: the task brief for this slice pointed at
 * `frontend/src/features/analytics/components/EChart.tsx` as a wrapper a
 * concurrent slice is building, to be imported rather than duplicated. That
 * path did not exist anywhere in this worktree when slice 034 landed (no
 * `features/analytics` directory at all), so per the brief's own fallback
 * this is a local, minimal wrapper with what seemed the obvious props for
 * the job. If `features/analytics/components/EChart.tsx` merges with a
 * different (or richer) prop shape, reconcile the two — most likely by
 * deleting this file and pointing `features/receiver`'s imports at the
 * shared one, keyed on the surface actually used here (`option`, `style`,
 * `className`, `ariaLabel`, `notMerge`).
 *
 * `echarts` is loaded whole (`import * as echarts`) rather than the
 * tree-shaken `core` + explicit chart/component registration ECharts'
 * own docs recommend, to keep this wrapper generic across every chart type
 * the Receiver page uses (line, bar, polar) without each caller having to
 * register its own renderer pieces. Revisit if bundle size becomes a
 * problem — `docs/DEVELOPMENT.md`'s Pi-class target budget is 049's gate,
 * not this slice's.
 */
import * as echarts from "echarts";
import { useEffect, useRef } from "react";

export interface EChartProps {
  /** A complete ECharts option object. Passed to `setOption` with
   * `notMerge` (default `true`) so a caller never has to worry about a
   * stale series lingering from a previous render. */
  option: echarts.EChartsCoreOption;
  className?: string;
  style?: React.CSSProperties;
  /** Accessible label for the chart's role="img" container. Every chart on
   * the Receiver page also renders a visible text summary beside it
   * (`docs/DEVELOPMENT.md` a11y baseline, SPEC §80) — this label is the
   * short form for a screen reader landing on the canvas itself. */
  ariaLabel: string;
  /** Re-render from scratch instead of diffing against the previous option.
   * Defaults to `true`: every chart here rebuilds its whole option from a
   * fresh query result, so there is no series identity worth preserving
   * across updates, and skipping the diff avoids ECharts merging stale
   * series left over from a different window/resolution selection. */
  notMerge?: boolean;
}

const DEFAULT_HEIGHT = 280;

/** Renders one ECharts instance into a `<div>`, sized to its container and
 * kept in sync with `option` and the browser window's size. */
export function EChart({
  option,
  className,
  style,
  ariaLabel,
  notMerge = true,
}: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const instance = echarts.init(container);
    instanceRef.current = instance;

    function handleResize() {
      instance.resize();
    }
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      instance.dispose();
      instanceRef.current = null;
    };
    // The instance is created once per mount; `option` updates below reuse it.
  }, []);

  useEffect(() => {
    instanceRef.current?.setOption(option, notMerge);
  }, [option, notMerge]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={ariaLabel}
      className={className}
      style={{ width: "100%", height: DEFAULT_HEIGHT, ...style }}
    />
  );
}
