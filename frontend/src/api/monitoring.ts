import { apiRequest } from "./client";
import type {

  MessageOutput,
} from "types";

/* ---------------- TYPES ---------------- */

export interface Dataset {
  id: number;
  name: string;
}

export interface Run {
  run_id: number;
}

export interface PerLabelMetrics {
  f1: number;
  precision: number;
  recall: number;
}

export interface EvaluationResponse {
  run_id: number;
  per_label: Record<string, PerLabelMetrics>;
}

export interface TrainingMetric {
  epoch: number;
  loss: number;
}

/* ---------------- DATASETS ---------------- */

export function getDatasets(token: string, page = 1, limit = 50) {
  return apiRequest<{ datasets: Dataset[] }>(
    `/datasets/?page=${page}&limit=${limit}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

export function getDatasetStats(datasetId: number, token: string) {
  return apiRequest<any>(
    `/bioner/datasets/${datasetId}/full-stats`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

/* ---------------- RUNS ---------------- */

export function getDatasetRuns(datasetId: number, token: string) {
  return apiRequest<Run[]>(
    `/bioner/datasets/${datasetId}/runs`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

export function getAllEvaluations(token: string) {
  return apiRequest<any[]>(
    `/bioner/evaluations`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

export function getRunEvaluation(runId: number, token: string) {
  return apiRequest<EvaluationResponse>(
    `/bioner/runs/${runId}/evaluation`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

export function getAllRunEvaluations(datasetId: number, token: string) {
  return apiRequest<any[]>(
    `/bioner/datasets/${datasetId}/runs/evaluations`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

/* ---------------- TRAINING ---------------- */

export function startTraining(payload: {
  dataset_id: number | null;
  labels: string[];
  base_model: string;
  token: string;
  val_ratio: number;
}) {
  return apiRequest<{ run_id: number }>(
    `/bioner/training/start`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${payload.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        dataset_id: payload.dataset_id,
        labels: payload.labels,
        base_model: payload.base_model,
        val_ratio: payload.val_ratio,
      }),
    }
  );
}

export function stopTraining(runId: number, token: string) {
  return apiRequest<MessageOutput>(
    `/bioner/training/stop/${runId}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

/* ---------------- WS ---------------- */

export function getTrainingWSUrl(token: string) {
  return `ws://localhost:8000/api/v1/bioner/ws/training?token=${token}`;
}