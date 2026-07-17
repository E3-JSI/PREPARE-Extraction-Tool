import { useMemo, useState } from "react";

import Button from "@components/Button";
import Card from "@components/Card";
import ProgressBar from "@components/ProgressBar";
import { Select } from "@components/Select";
import { useLiveEvalPolling } from "@hooks/useLiveEvalPolling";

import { useMonitor } from "../hooks/useMonitor";
import styles from "./LiveEvalPanel.module.css";

interface Props {
  modelId: number;
}

/** Format a 0–1 score as a percentage, or a dash when absent. */
const formatPct = (value?: number | null): string => (typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—");

/**
 * User-triggered live evaluation for a trained model: pick a dataset, run the
 * model over its held-out reviewed records, and see precision/recall/F1 against
 * the gold annotations. Runs as an async job (progress bar + cancel) and stores
 * its metrics separately from the base-vs-trained training-time evaluation.
 */
const LiveEvalPanel = ({ modelId }: Props) => {
  const { datasets, toast } = useMonitor();
  const [datasetId, setDatasetId] = useState<string>("");

  const { isRunning, isCancelling, progress, metrics, message, error, runLiveEval, cancelLiveEval } =
    useLiveEvalPolling(modelId);

  const options = useMemo(() => datasets.map((d) => ({ value: String(d.id), label: d.name })), [datasets]);

  const percent = progress && progress.total > 0 ? (progress.completed / progress.total) * 100 : 0;

  const handleRun = async () => {
    if (!datasetId) return;
    try {
      await runLiveEval(Number(datasetId));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      const isConflict = msg.includes("already running") || msg.startsWith("HTTP 409");
      toast.showToast(
        isConflict ? "An extraction or live-eval job is already running" : msg || "Failed to start live evaluation",
        "error"
      );
    }
  };

  const handleCancel = async () => {
    try {
      await cancelLiveEval();
    } catch {
      toast.showToast("Failed to cancel live evaluation", "error");
    }
  };

  const hasResults = metrics != null && metrics.labels.length > 0;
  const headlineF1 = metrics?.aggregate?.exact?.f1;

  return (
    <Card title="Live evaluation">
      <p className={styles.intro}>
        Run this model over a dataset's reviewed records it was not trained on, and score its predictions against the
        gold annotations. Results are kept separate from the training-time evaluation above.
      </p>

      <div className={styles.controls}>
        <Select
          options={options}
          value={datasetId}
          onValueChange={setDatasetId}
          placeholder="Select a dataset…"
          aria-label="Evaluation dataset"
          disabled={isRunning}
          fullWidth={false}
        />
        <Button variant="primary" size="small" onClick={handleRun} disabled={isRunning || !datasetId}>
          Run live eval
        </Button>
        {isRunning && (
          <Button variant="outline" size="small" colorScheme="danger" onClick={handleCancel} disabled={isCancelling}>
            {isCancelling ? "Cancelling…" : "Cancel"}
          </Button>
        )}
      </div>

      {isRunning && progress && (
        <div className={styles.progress}>
          <ProgressBar value={percent} />
          <span className={styles.progressText}>
            {progress.status === "pending"
              ? "Starting…"
              : `Scored ${progress.completed} of ${progress.total} record${progress.total === 1 ? "" : "s"}`}
          </span>
        </div>
      )}

      {error && <p className={styles.error}>{error}</p>}

      {!isRunning && !hasResults && message && <p className={styles.empty}>{message}</p>}

      {!isRunning && !hasResults && !message && !error && (
        <p className={styles.empty}>Pick a dataset and run a live evaluation to see per-label scores.</p>
      )}

      {hasResults && (
        <div className={styles.results}>
          <div className={styles.headline}>
            <span className={styles.headlineLabel}>Exact F1 (macro)</span>
            <span className={styles.headlineValue}>{formatPct(headlineF1)}</span>
            <span className={styles.headlineSub}>
              {metrics!.heldout_count} held-out record{metrics!.heldout_count === 1 ? "" : "s"}
            </span>
          </div>

          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Exact P</th>
                  <th>Exact R</th>
                  <th>Exact F1</th>
                  <th>Relaxed F1</th>
                  <th>Overlap F1</th>
                </tr>
              </thead>
              <tbody>
                {metrics!.labels.map((label) => {
                  const row = metrics!.per_label[label];
                  return (
                    <tr key={label}>
                      <td>{label}</td>
                      <td>{formatPct(row?.exact?.precision)}</td>
                      <td>{formatPct(row?.exact?.recall)}</td>
                      <td>{formatPct(row?.exact?.f1)}</td>
                      <td>{formatPct(row?.relaxed?.f1)}</td>
                      <td>{formatPct(row?.overlap?.f1)}</td>
                    </tr>
                  );
                })}
                <tr className={styles.aggregateRow}>
                  <td>Macro avg</td>
                  <td>{formatPct(metrics!.aggregate?.exact?.precision)}</td>
                  <td>{formatPct(metrics!.aggregate?.exact?.recall)}</td>
                  <td>{formatPct(metrics!.aggregate?.exact?.f1)}</td>
                  <td>{formatPct(metrics!.aggregate?.relaxed?.f1)}</td>
                  <td>{formatPct(metrics!.aggregate?.overlap?.f1)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
};

export default LiveEvalPanel;
