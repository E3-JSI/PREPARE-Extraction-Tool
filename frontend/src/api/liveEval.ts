import type { LiveEvalJobStartResponse, LiveEvalJobStatusResponse, MessageOutput } from "types";

import { apiRequest } from "./client";

// Note: auth is injected automatically by `apiRequest` from localStorage.

/** Start a live evaluation of a trained model over a dataset's held-out reviewed
 *  records. Returns immediately with a job id to poll (or a completed job with a
 *  message when there are no held-out records). */
export function startLiveEval(modelId: number, datasetId: number): Promise<LiveEvalJobStartResponse> {
  return apiRequest<LiveEvalJobStartResponse>("/bioner/live-eval/start", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, dataset_id: datasetId }),
  });
}

/** Progress (and, once done, metrics) for a live-eval job. */
export function getLiveEvalStatus(jobId: number): Promise<LiveEvalJobStatusResponse> {
  return apiRequest<LiveEvalJobStatusResponse>(`/bioner/live-eval/${jobId}/status`);
}

/** The caller's latest pending/running live-eval job, or null. */
export async function getActiveLiveEval(): Promise<LiveEvalJobStatusResponse | null> {
  const result = await apiRequest<LiveEvalJobStatusResponse | null>("/bioner/live-eval/active");
  // apiRequest returns {} for an empty 200 body; normalize "no active job" to null.
  return result?.job_id ? result : null;
}

/** Request cancellation of a live-eval job. Already-scored records remain. */
export function cancelLiveEval(jobId: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/bioner/live-eval/${jobId}/cancel`, { method: "POST" });
}
