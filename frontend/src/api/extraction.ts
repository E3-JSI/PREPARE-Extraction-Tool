import type { MessageOutput, ExtractionJobStartResponse, ExtractionJobStatusResponse } from "types";

import { apiRequest } from "./client";

export async function extractRecordTerms(
  datasetId: number,
  recordId: number,
  labels: string[]
): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/bioner/${datasetId}/records/${recordId}/extract`, {
    method: "POST",
    body: JSON.stringify({ labels }),
  });
}

export async function extractDatasetTerms(datasetId: number, labels: string[]): Promise<ExtractionJobStartResponse> {
  return apiRequest<ExtractionJobStartResponse>(`/bioner/${datasetId}/records/extract`, {
    method: "POST",
    body: JSON.stringify({ labels }),
  });
}

export async function getDatasetExtractionStatus(
  datasetId: number,
  jobId: string
): Promise<ExtractionJobStatusResponse> {
  return apiRequest<ExtractionJobStatusResponse>(`/bioner/${datasetId}/records/extract/${jobId}/status`);
}

export async function cancelDatasetExtraction(datasetId: number, jobId: string): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/bioner/${datasetId}/records/extract/${jobId}/cancel`, { method: "POST" });
}

export async function getActiveExtractionJob(
  datasetId: number
): Promise<ExtractionJobStatusResponse | null> {
  const result = await apiRequest<ExtractionJobStatusResponse | null>(
    `/bioner/${datasetId}/records/extract/active`
  );
  return result ?? null;
}
