import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

import { PREPARE_CHART_THEME } from "./theme";

export interface EChartProps {
  /** The ECharts option object describing the chart. */
  option: EChartsOption;
  /** Chart height in px (or any CSS size). Defaults to 300. */
  height?: number | string;
  /**
   * Replace the previous option instead of merging. Leave `false` for
   * incrementally-updated charts (e.g. live loss) so new data animates in;
   * set `true` when the series shape changes between renders.
   */
  notMerge?: boolean;
  className?: string;
}

/**
 * Thin wrapper around `echarts-for-react` that applies the shared PREPARE
 * theme and a responsive, full-width canvas. All chart primitives render
 * through this so theming and resize behavior stay consistent.
 */
const EChart = ({ option, height = 300, notMerge = false, className }: EChartProps) => (
  <ReactECharts
    option={option}
    theme={PREPARE_CHART_THEME}
    notMerge={notMerge}
    lazyUpdate
    style={{ height, width: "100%" }}
    className={className}
    opts={{ renderer: "canvas" }}
  />
);

export default EChart;
