import { apiRequest } from "./client";
import type {
  ActiveModelResponse,
  ActiveTrainingRun,
  DatasetsOutput,
  MessageOutput,
  ModelDetailResponse,
  ModelsOutput,
  ModelSummary,
  RescanModelsResponse,
  MonitorDatasetStats,
  MonitorRun,
  RunUpdate,
  TrainingMetric,
} from "types";

// Note: auth is injected automatically by `apiRequest` from localStorage.

/* ---------------- DATASETS ---------------- */

export function getDatasets(page = 1, limit = 50) {
  return apiRequest<DatasetsOutput>(`/datasets/?page=${page}&limit=${limit}`);
}

export function getDatasetStats(datasetId: number) {
  return apiRequest<MonitorDatasetStats>(`/bioner/datasets/${datasetId}/full-stats`);
}

/** Aggregated record/term counts and label distribution across multiple datasets. */
export function getMultiDatasetStats(datasetIds: number[]) {
  return apiRequest<MonitorDatasetStats>("/bioner/datasets/full-stats", {
    method: "POST",
    body: JSON.stringify({ dataset_ids: datasetIds }),
  });
}

/* ---------------- RUNS ---------------- */

/** Rename a run and/or mark it as the dataset's preferred run. */
export function updateRun(runId: number, payload: RunUpdate) {
  return apiRequest<MonitorRun>(`/bioner/runs/${runId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** Delete a run and its dependent metrics/model/evaluation rows. */
export function deleteRun(runId: number) {
  return apiRequest<MessageOutput>(`/bioner/runs/${runId}`, {
    method: "DELETE",
  });
}

/** Delete a model: its on-disk folder (via bioner) and its DB row. Works for
 * discovered models with no training run; the producing run is kept as history. */
export function deleteModel(modelId: number) {
  return apiRequest<MessageOutput>(`/bioner/models/${modelId}`, {
    method: "DELETE",
  });
}

/** Per-epoch loss curve for a single run, ordered by epoch. */
export function getRunMetrics(runId: number) {
  return apiRequest<TrainingMetric[]>(`/bioner/runs/${runId}/metrics`);
}

/** The current in-flight training run (null if none), used to rehydrate live
 * progress on the Monitor page after navigation or a full page reload. */
export function getActiveRun() {
  return apiRequest<ActiveTrainingRun | null>("/bioner/runs/active");
}

/* ---------------- MODELS ---------------- */

/** List trained models the user can select for NER extraction. */
export async function getModels(): Promise<ModelSummary[]> {
  const res = await apiRequest<ModelsOutput>("/bioner/models");
  return res.models;
}

/** Rescan bioner's models dir, reconcile the DB, and return the enriched list.
 *  This is the only write path for model discovery (upsert + delete-missing). */
export function rescanModels() {
  return apiRequest<RescanModelsResponse>("/bioner/models/rescan", {
    method: "POST",
  });
}

/** The GLOBAL active extraction model (null active_model = bioner default). */
export function getActiveModel() {
  return apiRequest<ActiveModelResponse>("/bioner/active-model");
}

/** Set (modelId) or clear (null = default) the GLOBAL active extraction model. */
export function setActiveModel(modelId: number | null) {
  return apiRequest<ActiveModelResponse>("/bioner/active-model", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  });
}

/** Per-model detail: training datasets, snapshot stats, base-vs-trained eval. */
export function getModelDetail(modelId: number) {
  return apiRequest<ModelDetailResponse>(`/bioner/models/${modelId}/detail`);
}

/* ---------------- TRAINING ---------------- */

export function startTraining(payload: {
  dataset_ids: number[];
  eval_dataset_ids: number[];
  labels: string[];
  base_model: string;
  val_ratio: number;
  num_epochs: number;
  learning_rate: number;
  train_batch_size: number;
}) {
  return apiRequest<{ run_id: number }>("/bioner/training/start", {
    method: "POST",
    body: JSON.stringify({
      dataset_ids: payload.dataset_ids,
      eval_dataset_ids: payload.eval_dataset_ids,
      labels: payload.labels,
      base_model: payload.base_model,
      val_ratio: payload.val_ratio,
      num_epochs: payload.num_epochs,
      learning_rate: payload.learning_rate,
      train_batch_size: payload.train_batch_size,
    }),
  });
}

export function stopTraining(runId: number) {
  return apiRequest<MessageOutput>(`/bioner/training/stop/${runId}`, {
    method: "POST",
  });
}

/* ---------------- WS ---------------- */

export function getTrainingWSUrl(token: string) {
  const backendHost = import.meta.env.VITE_BACKEND_HOST;
  let base: string;
  if (backendHost) {
    base = backendHost.replace(/^http/, "ws");
  } else {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    base = `${proto}://${window.location.host}`;
  }
  // NOTE: The access token is passed via the URL query string because the
  // browser WebSocket API cannot set custom request headers. The backend reads
  // `token` from the query. This is a known limitation: tokens in URLs can leak
  // into server/proxy access logs and browser history. encodeURIComponent keeps
  // the value safely encoded; a more robust approach would be a short-lived
  // one-time ticket or a subprotocol-based handshake instead of a long-lived
  // token in the URL.
  return `${base}/api/v1/bioner/ws/training?token=${encodeURIComponent(token)}`;
}
