import type { HeatmapCell } from "@components/charts";
import type { EvaluationResponse, PerLabelMetrics, TrainingMetric } from "types";

/** Selectable metric for the per-label and comparison views. */
export type MetricMode = "exact_f1" | "relaxed_f1" | "precision" | "recall";

export const METRIC_OPTIONS: { value: MetricMode; label: string }[] = [
  { value: "exact_f1", label: "Exact F1" },
  { value: "relaxed_f1", label: "Relaxed F1" },
  { value: "precision", label: "Precision" },
  { value: "recall", label: "Recall" },
];

/** Aggregate rows returned by the backend that should not appear as labels. */
const AGGREGATE_LABELS = new Set(["micro avg", "macro avg", "weighted avg"]);

/** Strip combining diacritics so label keys compare/sort consistently. */
export const normalizeLabel = (label: string): string => label.normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Read a single metric from a per-label entry, with sensible fallbacks. */
export const readMetric = (m: PerLabelMetrics, mode: MetricMode): number => {
  switch (mode) {
    case "exact_f1":
      return m.exact_f1 ?? m.f1 ?? 0;
    case "relaxed_f1":
      return m.relaxed_f1 ?? 0;
    case "precision":
      return m.precision ?? 0;
    case "recall":
      return m.recall ?? 0;
  }
};

const isLabelRow = (label: string): boolean => !AGGREGATE_LABELS.has(label.toLowerCase());

/** Loss curve data for the training line chart. */
export interface LossSeries {
  xData: number[];
  /** Train loss per x-point; null where only an eval point exists. */
  loss: (number | null)[];
  evalLoss: (number | null)[];
  /** True when any metric point carries a `step` value (prefer step over epoch on x-axis). */
  hasStep: boolean;
}

/**
 * Shape raw metric rows into aligned train/eval loss series for the line chart.
 *
 * The trainer streams a step's train loss and its eval loss as *separate* rows,
 * and (for some runs) also a redundant step-less `epoch_update` row carrying the
 * same loss. When any row has a `step`, that's the authoritative x-axis: we
 * coalesce rows sharing a step into one point (merging train + eval loss) and
 * drop the step-less orphans, so the two series overlay cleanly instead of the
 * orphans piling up as stray trailing x-categories.
 *
 * Legacy runs that only ever persisted step-less rows have no reliable unique x
 * (their fractional epochs are int-truncated, so values repeat). For those we
 * keep every row in order against its epoch label rather than collapsing
 * distinct loss points together.
 */
export const buildLossSeries = (metrics: TrainingMetric[]): LossSeries => {
  const hasStep = metrics.some((m) => m.step != null);

  if (!hasStep) {
    return {
      xData: metrics.map((m) => m.epoch),
      loss: metrics.map((m) => m.loss ?? null),
      evalLoss: metrics.map((m) => m.eval_loss ?? null),
      hasStep,
    };
  }

  const byStep = new Map<number, { loss: number | null; evalLoss: number | null }>();
  for (const m of metrics) {
    if (m.step == null) continue;
    const point = byStep.get(m.step) ?? { loss: null, evalLoss: null };
    if (m.loss != null) point.loss = m.loss;
    if (m.eval_loss != null) point.evalLoss = m.eval_loss;
    byStep.set(m.step, point);
  }

  const steps = [...byStep.keys()].sort((a, b) => a - b);
  return {
    xData: steps,
    loss: steps.map((s) => byStep.get(s)!.loss),
    evalLoss: steps.map((s) => byStep.get(s)!.evalLoss),
    hasStep,
  };
};

/** Format an epoch (often fractional during a run) as a compact number. */
export const formatEpoch = (value: string | number): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, "");
};

/** Format a loss value to a fixed precision for axes and tooltips. */
export const formatLoss = (value: number): string => (Number.isFinite(value) ? value.toFixed(4) : String(value));

/** Per-label evaluation data for the grouped bar chart. */
export interface PerformanceData {
  categories: string[];
  exactF1: number[];
  relaxedF1: number[];
  precision: number[];
  recall: number[];
}

export const buildPerformanceData = (evaluation: EvaluationResponse | null): PerformanceData => {
  const entries = Object.entries(evaluation?.per_label ?? {}).filter(([label]) => isLabelRow(label));

  return {
    categories: entries.map(([label]) => label),
    exactF1: entries.map(([, m]) => m.exact_f1 ?? m.f1 ?? 0),
    relaxedF1: entries.map(([, m]) => m.relaxed_f1 ?? 0),
    precision: entries.map(([, m]) => m.precision ?? 0),
    recall: entries.map(([, m]) => m.recall ?? 0),
  };
};

/** Run-vs-label comparison matrix for the heatmap. */
export interface ComparisonMatrix {
  /** Column labels (entity labels). */
  xLabels: string[];
  /** Row labels (one per run). */
  yLabels: string[];
  /** Cells keyed by [labelIndex, runIndex]. */
  cells: HeatmapCell[];
}

export const buildComparisonMatrix = (evaluations: EvaluationResponse[], mode: MetricMode): ComparisonMatrix => {
  const xLabels = Array.from(
    new Set(
      evaluations.flatMap((run) =>
        Object.keys(run?.per_label ?? {})
          .filter(isLabelRow)
          .map(normalizeLabel)
      )
    )
  ).sort();

  const yLabels = evaluations.map((run) => run.name ?? `Run #${run.run_id}`);

  const cells: HeatmapCell[] = [];
  evaluations.forEach((run, y) => {
    // collapse normalized-label collisions, keeping the first value seen
    const byLabel = new Map<string, number>();
    Object.entries(run?.per_label ?? {}).forEach(([label, metrics]) => {
      if (!isLabelRow(label)) return;
      const norm = normalizeLabel(label);
      if (!byLabel.has(norm)) byLabel.set(norm, readMetric(metrics, mode));
    });

    xLabels.forEach((label, x) => {
      cells.push({ x, y, value: byLabel.get(label) ?? 0 });
    });
  });

  return { xLabels, yLabels, cells };
};
