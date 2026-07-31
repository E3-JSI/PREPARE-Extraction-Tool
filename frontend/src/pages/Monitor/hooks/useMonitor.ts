import { createContext, useContext } from "react";

import type { ToastApi } from "@hooks/useToast";
import type { MonitorDataset, MonitorDatasetStats, TrainingMetric } from "types";

export const DEFAULT_MODEL = "urchade/gliner_multi-v2.1";

export type MonitorView = "models" | "training";

/**
 * The shared Monitor contract. Both `index.tsx` and the view components
 * (ModelsView / TrainingView) consume this via `useMonitor()`. The shape is
 * frozen so the views can be developed independently against it.
 */
export interface MonitorContextValue {
  // ── view toggle ──
  activeView: MonitorView;
  setActiveView: (view: MonitorView) => void;

  // ── datasets ──
  datasets: MonitorDataset[];
  /** Aggregated stats across the selected TRAINING datasets. */
  trainingStats: MonitorDatasetStats | null;

  // ── training state ──
  isTraining: boolean;
  progress: number;
  currentStep: number;
  totalSteps: number;
  trainingMetrics: TrainingMetric[];
  /** Live pre-training phase ("loading" | "baseline" | "init" | "training"),
   *  or null when no run is in flight. Drives the progress phase stepper. */
  trainingPhase: string | null;

  // ── training config ──
  /** Datasets to train on (first = primary). */
  trainingDatasetIds: number[];
  setTrainingDatasetIds: (ids: number[]) => void;
  /** Optional datasets to evaluate against instead of a held-out split. */
  evalDatasetIds: number[];
  setEvalDatasetIds: (ids: number[]) => void;
  selectedLabels: string[];
  setSelectedLabels: (labels: string[]) => void;
  valSplitRatio: number;
  setValSplitRatio: (ratio: number) => void;
  baseModel: string;
  setBaseModel: (model: string) => void;
  customModel: string;
  setCustomModel: (model: string) => void;
  useCustomModel: boolean;
  setUseCustomModel: (use: boolean) => void;
  // ── hyperparameters ──
  numEpochs: number;
  setNumEpochs: (n: number) => void;
  learningRate: number;
  setLearningRate: (lr: number) => void;
  trainBatchSize: number;
  setTrainBatchSize: (n: number) => void;

  // ── actions ──
  startTraining: () => Promise<void>;
  stopTraining: () => Promise<void>;

  // ── feedback ──
  /** Stable toast API; the toast state + container live in `ToastProvider`. */
  toast: ToastApi;
}

export const MonitorContext = createContext<MonitorContextValue | null>(null);

/** Access the shared Monitor state. Must be used within a `MonitorProvider`. */
export const useMonitor = (): MonitorContextValue => {
  const ctx = useContext(MonitorContext);
  if (!ctx) {
    throw new Error("useMonitor must be used within a MonitorProvider");
  }
  return ctx;
};
