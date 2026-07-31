import type { EChartsOption } from "echarts";

import EChart from "../EChart";

export interface BarSeries {
  /** Series label shown in the legend and tooltip. */
  name: string;
  /** Values aligned by index with `categories`. */
  data: number[];
  /** Optional explicit bar color (defaults to the theme palette). */
  color?: string;
}

export interface BarChartProps {
  /** Category labels along the x-axis. */
  categories: string[];
  /** One or more grouped bar series. */
  series: BarSeries[];
  height?: number;
  yMin?: number;
  yMax?: number;
  yName?: string;
  showLegend?: boolean;
  /** Rotate x-axis labels by this angle (useful for long category names). */
  xLabelRotate?: number;
}

/** Generic grouped/categorical bar chart. */
const BarChart = ({
  categories,
  series,
  height = 300,
  yMin,
  yMax,
  yName,
  showLegend = true,
  xLabelRotate = 0,
}: BarChartProps) => {
  const option: EChartsOption = {
    grid: { left: 8, right: 16, top: showLegend ? 36 : 16, bottom: 8, containLabel: true },
    legend: showLegend ? { top: 0 } : undefined,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "category",
      data: categories,
      axisLabel: { rotate: xLabelRotate, interval: 0 },
    },
    yAxis: { type: "value", name: yName, min: yMin, max: yMax },
    series: series.map((s) => ({
      name: s.name,
      type: "bar",
      data: s.data,
      itemStyle: { color: s.color, borderRadius: [3, 3, 0, 0] },
    })),
  };

  return <EChart option={option} height={height} notMerge />;
};

export default BarChart;
