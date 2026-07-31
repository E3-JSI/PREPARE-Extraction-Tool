import type { EChartsOption } from "echarts";

import EChart from "../EChart";
import { CHART_TOKENS } from "../theme";

export interface HeatmapCell {
  /** Column index into `xLabels`. */
  x: number;
  /** Row index into `yLabels`. */
  y: number;
  /** Cell value (drives the color scale). */
  value: number;
}

export interface HeatmapProps {
  /** Column labels (x-axis). */
  xLabels: string[];
  /** Row labels (y-axis). */
  yLabels: string[];
  /** Cell values. */
  data: HeatmapCell[];
  height?: number;
  min?: number;
  max?: number;
  /** Low/high gradient endpoints. Defaults to error → success tokens. */
  lowColor?: string;
  highColor?: string;
  /** Print the value inside each cell. Defaults to true. */
  showLabel?: boolean;
  /** Format a value for the in-cell label and tooltip. */
  valueFormatter?: (value: number) => string;
  /** Build the tooltip body for a cell. */
  tooltipFormatter?: (cell: { xLabel: string; yLabel: string; value: number }) => string;
}

const defaultFormat = (v: number) => v.toFixed(3);

/** Generic matrix heatmap with a continuous color scale. */
const Heatmap = ({
  xLabels,
  yLabels,
  data,
  height = 360,
  min = 0,
  max = 1,
  lowColor = CHART_TOKENS.error,
  highColor = CHART_TOKENS.success,
  showLabel = true,
  valueFormatter = defaultFormat,
  tooltipFormatter,
}: HeatmapProps) => {
  const option: EChartsOption = {
    grid: { left: 8, right: 16, top: 8, bottom: 24, containLabel: true },
    tooltip: {
      position: "top",
      formatter: (params: unknown) => {
        const p = params as { value: [number, number, number] };
        const [x, y, value] = p.value;
        const xLabel = xLabels[x];
        const yLabel = yLabels[y];
        if (tooltipFormatter) return tooltipFormatter({ xLabel, yLabel, value });
        return `${yLabel} · ${xLabel}<br/><b>${valueFormatter(value)}</b>`;
      },
    },
    xAxis: {
      type: "category",
      data: xLabels,
      splitArea: { show: true },
      axisLabel: { rotate: xLabels.length > 6 ? 30 : 0, interval: 0 },
    },
    yAxis: { type: "category", data: yLabels, splitArea: { show: true } },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: { color: [lowColor, highColor] },
      textStyle: { color: CHART_TOKENS.textMuted },
    },
    series: [
      {
        type: "heatmap",
        data: data.map((c) => [c.x, c.y, c.value]),
        label: {
          show: showLabel,
          formatter: (params: unknown) => {
            const p = params as { value: [number, number, number] };
            return valueFormatter(p.value[2]);
          },
          color: CHART_TOKENS.surface,
          fontSize: 11,
        },
        itemStyle: { borderColor: CHART_TOKENS.surface, borderWidth: 1 },
      },
    ],
  };

  return <EChart option={option} height={height} notMerge />;
};

export default Heatmap;
