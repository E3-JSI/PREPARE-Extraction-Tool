import type {
  ClustersOutput,
  ClusterData,
  ClusterCreateRequest,
  ClusterMergeRequest,
  ClusterJobStartResponse,
  ClusterJobStatusResponse,
  MessageOutput,
} from "types";

import { apiRequest, getToken, API_BASE_URL } from "./client";

export async function getClusters(datasetId: number, label?: string): Promise<ClustersOutput> {
  const params = label ? `?label=${encodeURIComponent(label)}` : "";
  return apiRequest<ClustersOutput>(`/datasets/${datasetId}/clusters${params}`);
}

export async function rebuildClusters(datasetId: number, label: string): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/clusters/create?label=${encodeURIComponent(label)}`, {
    method: "POST",
  });
}

export async function startClusterAll(datasetId: number): Promise<ClusterJobStartResponse> {
  return apiRequest<ClusterJobStartResponse>(`/datasets/${datasetId}/clusters/cluster-all`, {
    method: "POST",
  });
}

export async function getClusterAllStatus(datasetId: number, jobId: string): Promise<ClusterJobStatusResponse> {
  return apiRequest<ClusterJobStatusResponse>(`/datasets/${datasetId}/clusters/cluster-all/${jobId}/status`);
}

export async function getActiveClusterJob(datasetId: number): Promise<ClusterJobStatusResponse | null> {
  const result = await apiRequest<ClusterJobStatusResponse | null>(
    `/datasets/${datasetId}/clusters/cluster-all/active`
  );
  // apiRequest returns {} for an empty 200 body, so normalize the "no active job"
  // case (null, undefined, or an empty/jobless object) to null.
  return result?.job_id ? result : null;
}

export async function cancelClusterJob(datasetId: number, jobId: string): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/clusters/cluster-all/${jobId}/cancel`, { method: "POST" });
}

export async function createCluster(datasetId: number, data: ClusterCreateRequest): Promise<ClusterData> {
  return apiRequest<ClusterData>(`/datasets/${datasetId}/clusters`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function assignTermToCluster(termId: number, clusterId: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/source-terms/${termId}/map-cluster/${clusterId}`, { method: "POST" });
}

export async function unassignTermFromCluster(termId: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/source-terms/${termId}/unmap-cluster`, {
    method: "POST",
  });
}

export async function renameCluster(clusterId: number, title: string): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/clusters/${clusterId}?title=${encodeURIComponent(title)}`, { method: "PUT" });
}

export async function mergeClusters(datasetId: number, data: ClusterMergeRequest): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/clusters/merge`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function deleteCluster(clusterId: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/clusters/${clusterId}`, {
    method: "DELETE",
  });
}

export async function updateClusterLabel(clusterId: number, label: string, color?: string): Promise<void> {
  return apiRequest<void>(`/clusters/${clusterId}/label`, {
    method: "PUT",
    body: JSON.stringify({ label, color }),
  });
}

export async function reviewLabel(datasetId: number, label: string): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/clusters/review-label`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export async function unreviewLabel(datasetId: number, label: string): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/clusters/unreview-label`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export async function downloadClusters(datasetId: number, label?: string): Promise<void> {
  const token = getToken();
  const headers: HeadersInit = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const params = label ? `?label=${encodeURIComponent(label)}` : "";
  const response = await fetch(`${API_BASE_URL}/datasets/${datasetId}/clusters/download${params}`, { headers });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Download failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  const contentDisposition = response.headers.get("Content-Disposition");
  const filenameMatch = contentDisposition?.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch ? filenameMatch[1] : `clusters_${datasetId}.json`;

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => window.URL.revokeObjectURL(url), 0);
}
