import type {
  ClusterMappingsOutput,
  ConceptSearchResults,
  ConceptHierarchy,
  AutoMapRequest,
  MapClusterRequest,
  AutoMapAllRequest,
  MappingJobStartResponse,
  MappingJobStatusResponse,
  ConceptSearchParams,
  MessageOutput,
} from "types";

import { apiRequest, getToken, API_BASE_URL } from "./client";

export async function getDatasetMappings(datasetId: number, label?: string): Promise<ClusterMappingsOutput> {
  const params = label ? `?label=${encodeURIComponent(label)}` : "";
  return apiRequest<ClusterMappingsOutput>(`/datasets/${datasetId}/mappings${params}`);
}

export async function autoMapCluster(
  datasetId: number,
  clusterId: number,
  request: AutoMapRequest
): Promise<ConceptSearchResults> {
  return apiRequest<ConceptSearchResults>(`/datasets/${datasetId}/clusters/${clusterId}/auto-map`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function mapClusterToConcept(
  datasetId: number,
  clusterId: number,
  request: MapClusterRequest
): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/clusters/${clusterId}/map`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function deleteClusterMapping(datasetId: number, clusterId: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/clusters/${clusterId}/mapping`, {
    method: "DELETE",
  });
}

// Auto-map-all runs as a backend async job: start returns a job id, then the
// client polls status for a progress bar (mirrors the extraction job endpoints).
export async function startAutoMapAll(datasetId: number, request: AutoMapAllRequest): Promise<MappingJobStartResponse> {
  return apiRequest<MappingJobStartResponse>(`/datasets/${datasetId}/auto-map-all`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function getAutoMapAllStatus(datasetId: number, jobId: string): Promise<MappingJobStatusResponse> {
  return apiRequest<MappingJobStatusResponse>(`/datasets/${datasetId}/auto-map-all/${jobId}/status`);
}

export async function getActiveAutoMapJob(datasetId: number): Promise<MappingJobStatusResponse | null> {
  const result = await apiRequest<MappingJobStatusResponse | null>(`/datasets/${datasetId}/auto-map-all/active`);
  // apiRequest returns {} for an empty 200 body, so normalize the "no active job"
  // case (null, undefined, or an empty/jobless object) to null.
  return result?.job_id ? result : null;
}

export async function cancelAutoMapJob(datasetId: number, jobId: string): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/auto-map-all/${jobId}/cancel`, { method: "POST" });
}

export async function searchConcepts(params: ConceptSearchParams): Promise<ConceptSearchResults> {
  const queryParams = new URLSearchParams({
    query: params.query,
    vocabulary_ids: params.vocabulary_ids.join(","),
    limit: (params.limit || 10).toString(),
    offset: (params.offset || 0).toString(),
  });

  if (params.domain_id) {
    queryParams.append("domain_id", params.domain_id);
  }
  if (params.concept_class_id) {
    queryParams.append("concept_class_id", params.concept_class_id);
  }
  if (params.standard_concept) {
    queryParams.append("standard_concept", params.standard_concept);
  }
  if (params.search_type) {
    queryParams.append("search_type", params.search_type);
  }
  if (params.sort_by) {
    queryParams.append("sort_by", params.sort_by);
  }
  if (params.sort_order) {
    queryParams.append("sort_order", params.sort_order);
  }

  return apiRequest<ConceptSearchResults>(`/datasets/concepts/search?${queryParams.toString()}`);
}

export async function getConceptHierarchy(conceptId: number): Promise<ConceptHierarchy> {
  return apiRequest<ConceptHierarchy>(`/datasets/concepts/${conceptId}/hierarchy`);
}

export async function exportMappings(datasetId: number, statusFilter?: string): Promise<void> {
  const token = getToken();
  const headers: HeadersInit = {};

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const params = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  const response = await fetch(`${API_BASE_URL}/datasets/${datasetId}/mappings/export${params}`, { headers });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Export failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  // Get filename from Content-Disposition header or use default
  const contentDisposition = response.headers.get("Content-Disposition");
  const filenameMatch = contentDisposition?.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch ? filenameMatch[1] : `mappings_${datasetId}.zip`;

  // Create blob and trigger download
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

export async function importMappings(datasetId: number, file: File): Promise<MessageOutput> {
  const formData = new FormData();
  formData.append("file", file);

  const token = getToken();
  const headers: HeadersInit = {};

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/datasets/${datasetId}/mappings/import`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Import failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}
