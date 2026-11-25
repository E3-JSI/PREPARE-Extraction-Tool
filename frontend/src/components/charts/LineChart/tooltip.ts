/** Item shape ECharts passes to an axis-trigger tooltip formatter. */
export interface AxisTooltipItem {
  marker: string;
  seriesName: string;
  value: number | Array<number | string | null>;
  axisValue: string | number;
}

/**
 * Build the axis tooltip body with formatted header and series values.
 *
 * Category-axis charts provide a single Y value. Value-axis charts provide
 * an [x, y] pair, so the second value is used for the tooltip body.
 */
export const buildAxisTooltipFormatter =
  (
    valueFormatter?: (value: number) => string,
    xAxisFormatter?: (value: string) => string
  ) =>
  (params: unknown): string => {
    const items = params as AxisTooltipItem[];
    if (!items.length) return "";

    const rawAxisValue = String(items[0].axisValue);
    const header = xAxisFormatter
      ? xAxisFormatter(rawAxisValue)
      : rawAxisValue;

    const rows = items
      .map((item) => {
        const rawValue = Array.isArray(item.value)
          ? item.value[1]
          : item.value;

        const numericValue =
          rawValue == null ? Number.NaN : Number(rawValue);

        return {
          item,
          numericValue,
        };
      })
      .filter(({ numericValue }) => Number.isFinite(numericValue))
      .map(({ item, numericValue }) => {
        const value = valueFormatter
          ? valueFormatter(numericValue)
          : String(numericValue);

        return `${item.marker}${item.seriesName}: <b>${value}</b>`;
      })
      .join("<br/>");

    return `${header}<br/>${rows}`;
  };