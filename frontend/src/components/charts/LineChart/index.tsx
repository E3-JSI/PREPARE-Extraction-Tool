import type { EChartsOption } from "echarts";

import EChart from "../EChart";
import { buildAxisTooltipFormatter } from "./tooltip";

export interface LineSeries {
  /** Series label shown in the legend and tooltip. */
  name: string;
  /** Y values, aligned by index with `xData`. Null entries render as gaps. */
  data: (number | null)[];
  /** Optional explicit line color (defaults to the theme palette). */
  color?: string;
  /** Smooth the line. Defaults to true. */
  smooth?: boolean;
  /** Fill the area under the line. */
  area?: boolean;
  /** Draw the line across null gaps (for series with sparse points). */
  connectNulls?: boolean;
}

export interface LineChartProps {
  /** Category values along the x-axis. */
  xData: Array<string | number>;
  /** One or more line series. */
  series: LineSeries[];
  height?: number;
  xName?: string;
  yName?: string;
  yMin?: number;
  yMax?: number;
  showLegend?: boolean;
  /** See {@link EChart}. Defaults to false so live data animates in. */
  notMerge?: boolean;
  /** Format y-values for the y-axis labels and tooltip series values. */
  valueFormatter?: (value: number) => string;
  /** Format x-axis category labels and the tooltip header. */
  xAxisFormatter?: (value: string) => string;
}

/** Generic multi-series line chart. */
const LineChart = ({
  xData,
  series,
  height = 300,
  xName,
  yName,
  yMin,
  yMax,
  showLegend = true,
  notMerge,
  valueFormatter,
  xAxisFormatter,
}: LineChartProps) => {
  const option: EChartsOption = {
    grid: { left: 8, right: 16, top: showLegend ? 36 : 16, bottom: 8, containLabel: true },
    legend: showLegend ? { top: 0 } : undefined,
    tooltip: {
      trigger: "axis",
      // Build the body ourselves so both the header (x) and series values (y) are formatted.
      formatter:
        valueFormatter || xAxisFormatter ? buildAxisTooltipFormatter(valueFormatter, xAxisFormatter) : undefined,
    },
    xAxis: {
      type: "category",
      data: xData.map(String),
      name: xName,
      boundaryGap: false,
      axisLabel: xAxisFormatter ? { formatter: (value: string) => xAxisFormatter(value) } : undefined,
    },
    yAxis: {
      type: "value",
      name: yName,
      min: yMin,
      max: yMax,
      axisLabel: valueFormatter ? { formatter: (value: number) => valueFormatter(value) } : undefined,
    },
    series: series.map((s) => ({
      name: s.name,
      type: "line",
      data: s.data,
      smooth: s.smooth ?? true,
      showSymbol: false,
      connectNulls: s.connectNulls ?? false,
      lineStyle: s.color ? { color: s.color, width: 2 } : { width: 2 },
      itemStyle: s.color ? { color: s.color } : undefined,
      areaStyle: s.area ? { opacity: 0.08 } : undefined,
    })),
  };

  return <EChart option={option} height={height} notMerge={notMerge} />;
};

export default LineChart;
