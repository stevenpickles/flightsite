/**
 * Registers the modular ECharts pieces the Analytics and Receiver pages'
 * charts actually use — `import * as echarts from "echarts"` would pull in
 * every chart type, every component and the SVG renderer none of these
 * charts need, which is exactly what roadmap slice 032 asks this module to
 * avoid (route-level lazy loading keeps it out of the Live Map bundle in the
 * first place; this keeps each chunk that imports it lean once loaded).
 *
 * `PolarComponent` — and with it `angleAxis`/`radiusAxis`, ECharts registers
 * the two together (they are the polar coordinate system's own axes, not
 * separate top-level components) — is here for roadmap slice 034's
 * range-by-bearing polar plot; every other entry is slice 032's original set.
 *
 * `EChart.tsx` imports this module once for its side effect (`echarts.use`)
 * before the first `echarts.init` call.
 */
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  PolarComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  PolarComponent,
  TooltipComponent,
  CanvasRenderer,
]);
