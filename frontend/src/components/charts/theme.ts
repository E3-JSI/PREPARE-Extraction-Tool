import * as echarts from "echarts";

/**
 * Brand color tokens mirrored from `src/index.css` (`:root`).
 *
 * ECharts renders to a canvas and cannot read CSS custom properties, so the
 * concrete hex values live here as the single source of truth for every chart.
 * Keep these in sync with the `--color-*` tokens in `index.css`.
 */
export const CHART_TOKENS = {
  primary: "#144d70",
  primaryDark: "#11415e",
  success: "#269b6f",
  error: "#dc2626",
  info: "#3b82f6",
  warning: "#f59e0b",
  text: "#374151",
  textMuted: "#6b7280",
  border: "#e5e7eb",
  surface: "#ffffff",
  surfaceAlt: "#f9fafb",
} as const;

export const CHART_FONT_FAMILY = "'Nunito Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif";

/** Default categorical palette for multi-series charts. */
export const CHART_PALETTE = [
  CHART_TOKENS.primary,
  CHART_TOKENS.success,
  CHART_TOKENS.info,
  CHART_TOKENS.warning,
  CHART_TOKENS.error,
];

/** Registered ECharts theme name — pass to `<ReactECharts theme={...} />`. */
export const PREPARE_CHART_THEME = "prepare";

const axisCommon = {
  axisLine: { lineStyle: { color: CHART_TOKENS.border } },
  axisTick: { lineStyle: { color: CHART_TOKENS.border } },
  axisLabel: { color: CHART_TOKENS.textMuted, fontFamily: CHART_FONT_FAMILY },
  splitLine: { lineStyle: { color: CHART_TOKENS.border, type: "dashed" } },
  nameTextStyle: { color: CHART_TOKENS.textMuted, fontFamily: CHART_FONT_FAMILY },
};

/**
 * Register the shared PREPARE theme once at module load. Importing this module
 * (directly or via a chart primitive) is enough to make the theme available.
 */
echarts.registerTheme(PREPARE_CHART_THEME, {
  color: CHART_PALETTE,
  backgroundColor: "transparent",
  textStyle: { fontFamily: CHART_FONT_FAMILY, color: CHART_TOKENS.text },
  title: { textStyle: { color: CHART_TOKENS.text, fontFamily: CHART_FONT_FAMILY } },
  legend: {
    textStyle: { color: CHART_TOKENS.textMuted, fontFamily: CHART_FONT_FAMILY },
    icon: "roundRect",
  },
  tooltip: {
    backgroundColor: CHART_TOKENS.text,
    borderWidth: 0,
    padding: [8, 12],
    textStyle: { color: CHART_TOKENS.surface, fontFamily: CHART_FONT_FAMILY, fontSize: 13 },
    axisPointer: {
      lineStyle: { color: CHART_TOKENS.border },
      crossStyle: { color: CHART_TOKENS.border },
    },
  },
  categoryAxis: axisCommon,
  valueAxis: axisCommon,
  logAxis: axisCommon,
  timeAxis: axisCommon,
});
