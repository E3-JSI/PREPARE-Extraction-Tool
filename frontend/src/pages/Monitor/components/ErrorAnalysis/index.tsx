import { useState } from "react";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronRight } from "@fortawesome/free-solid-svg-icons";

import { ChartState } from "@components/charts";
import type { ErrorExample, RunErrorAnalysis } from "types";

import { normalizeLabel } from "../../chartData";
import styles from "./styles.module.css";

const CHART_HEIGHT = 200;

/** Aggregate rows returned by the backend that should not appear as labels. */
const AGGREGATE_LABELS = new Set(["micro avg", "macro avg", "weighted avg"]);

/** Format a 0–1 score as a percentage, or a dash when absent. */
const formatPct = (value?: number | null): string => (typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—");

/** A single example error: context text with the gold (missed) or predicted
 * (wrong) span highlighted. Falls back to plain text + span when offsets are
 * unusable (e.g. after truncation). */
const ExampleItem = ({ example }: { example: ErrorExample }) => {
  const isMissed = example.gold !== null;
  const span = example.gold ?? example.predicted;
  const spanClass = isMissed ? styles.goldSpan : styles.predSpan;

  const offsetsUsable = span !== null && span.start >= 0 && span.end <= example.text.length && span.start < span.end;

  return (
    <div className={styles.example}>
      <span className={isMissed ? styles.badgeFn : styles.badgeFp}>
        {isMissed ? "Missed (FN)" : "False positive (FP)"}
      </span>
      {offsetsUsable ? (
        <p className={styles.exampleText}>
          {example.text.slice(0, span!.start)}
          <mark className={spanClass}>{example.text.slice(span!.start, span!.end)}</mark>
          {example.text.slice(span!.end)}
        </p>
      ) : (
        <p className={styles.exampleText}>
          {example.text}
          {span && (
            <>
              {" "}
              <mark className={spanClass}>{span.text}</mark>
            </>
          )}
        </p>
      )}
    </div>
  );
};

interface Props {
  errorAnalysis: RunErrorAnalysis | null;
  loading?: boolean;
  /** Whether a run is currently selected. */
  hasSelectedRun: boolean;
}

/**
 * Per-label error-analysis drill-down: an expandable row per label showing
 * precision/recall and false-positive/false-negative counts, expanding to a
 * bounded sample of concrete example errors with the offending span highlighted.
 */
const ErrorAnalysis = ({ errorAnalysis, loading, hasSelectedRun }: Props) => {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (loading) {
    return <ChartState variant="loading" message="Loading error analysis…" height={CHART_HEIGHT} />;
  }

  if (!hasSelectedRun) {
    return (
      <ChartState
        variant="empty"
        title="No run selected"
        message="Pick a run above to inspect where it makes mistakes."
        height={CHART_HEIGHT}
      />
    );
  }

  if (!errorAnalysis || !errorAnalysis.available) {
    return (
      <ChartState
        variant="empty"
        title="Error analysis not available"
        message="This run was trained before per-label error analysis was recorded. Re-train to capture it."
        height={CHART_HEIGHT}
      />
    );
  }

  const labels = Object.keys(errorAnalysis.per_label)
    .filter((label) => !AGGREGATE_LABELS.has(label.toLowerCase()))
    .sort();

  if (labels.length === 0) {
    return (
      <ChartState
        variant="empty"
        title="No labels"
        message="This run has no per-label error data."
        height={CHART_HEIGHT}
      />
    );
  }

  const toggle = (label: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });

  return (
    <div className={styles.list}>
      {labels.map((label) => {
        const metrics = errorAnalysis.per_label[label];
        const hasExamples = metrics.examples.length > 0;
        const isOpen = expanded.has(label);
        return (
          <div key={label} className={styles.row}>
            <button
              type="button"
              className={styles.header}
              onClick={() => hasExamples && toggle(label)}
              aria-expanded={hasExamples ? isOpen : undefined}
              disabled={!hasExamples}
            >
              <span className={styles.chevron}>
                {hasExamples && <FontAwesomeIcon icon={isOpen ? faChevronDown : faChevronRight} />}
              </span>
              <span className={styles.label}>{normalizeLabel(label)}</span>
              <span className={styles.stats}>
                <span title="Precision">P {formatPct(metrics.precision)}</span>
                <span title="Recall">R {formatPct(metrics.recall)}</span>
                <span className={styles.fp} title="False positives">
                  FP {metrics.fp ?? 0}
                </span>
                <span className={styles.fn} title="False negatives">
                  FN {metrics.fn ?? 0}
                </span>
              </span>
            </button>
            {isOpen && hasExamples && (
              <div className={styles.examples}>
                {metrics.examples.map((example, i) => (
                  <ExampleItem key={i} example={example} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default ErrorAnalysis;
