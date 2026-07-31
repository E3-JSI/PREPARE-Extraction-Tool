import { CHART_TOKENS } from "@components/charts";

/** Chart color palette for the monitoring dashboard.
 *
 * Derived from the shared `CHART_TOKENS` (mirrored from `src/index.css`) so the
 * dashboard charts stay in sync with the global brand palette.
 */
export const CHART = {
  loss: CHART_TOKENS.error,
  precision: CHART_TOKENS.primary,
  recall: CHART_TOKENS.info,
  exactF1: CHART_TOKENS.success,
  relaxedF1: CHART_TOKENS.warning,
} as const;
