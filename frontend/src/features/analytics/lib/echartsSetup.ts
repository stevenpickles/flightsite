/**
 * Registers the modular ECharts pieces the Analytics page's charts actually
 * use — `import * as echarts from "echarts"` would pull in every chart type,
 * every component and the SVG renderer none of these cards need, which is
 * exactly what roadmap slice 032 asks this module to avoid (route-level lazy
 * loading keeps it out of the Live Map bundle in the first place; this keeps
 * the Analytics chunk itself lean once loaded).
 *
 * `EChart.tsx` imports this module once for its side effect (`echarts.use`)
 * before the first `echarts.init` call.
 */
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);
