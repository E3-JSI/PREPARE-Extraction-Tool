/** Item shape ECharts passes to an axis-trigger tooltip formatter. */
export interface AxisTooltipItem {
  marker: string;
  seriesName: string;
  value: number;
  axisValue: string;
}

/**
 * Build the axis tooltip body with formatted header (x) and series values (y).
 *
 * Series with no data at the hovered x are skipped: ECharts stores `null`
 * points as `NaN` internally, so a sparse series (e.g. eval loss emitted only
 * every `eval_steps` steps) would otherwise show "Eval loss: NaN" on every
 * other step.
 */
export const buildAxisTooltipFormatter =
  (valueFormatter?: (value: number) => string, xAxisFormatter?: (value: string) => string) =>
  (params: unknown): string => {
    const items = params as AxisTooltipItem[];
    if (!items.length) return "";
    const header = xAxisFormatter ? xAxisFormatter(items[0].axisValue) : items[0].axisValue;
    const rows = items
      .filter((it) => Number.isFinite(Number(it.value)))
      .map((it) => {
        const val = valueFormatter ? valueFormatter(Number(it.value)) : String(it.value);
        return `${it.marker}${it.seriesName}: <b>${val}</b>`;
      })
      .join("<br/>");
    return `${header}<br/>${rows}`;
  };
