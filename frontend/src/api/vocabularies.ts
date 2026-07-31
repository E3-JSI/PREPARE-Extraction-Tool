import type {
  VocabulariesOutput,
  VocabularyOutput,
  VocabularyUploadResponse,
  VocabularyCreate,
  MessageOutput,
  ConceptsOutput,
  DistinctValuesOutput,
} from "types";

import { apiRequest, getToken, API_BASE_URL } from "./client";

export async function getVocabularies(page = 1, limit = 50): Promise<VocabulariesOutput> {
  return apiRequest<VocabulariesOutput>(`/vocabularies/?page=${page}&limit=${limit}`);
}

export async function getVocabulary(id: number): Promise<VocabularyOutput> {
  return apiRequest<VocabularyOutput>(`/vocabularies/${id}`);
}

export async function createVocabulary(
  data: VocabularyCreate,
  onProgress?: (progress: number) => void
): Promise<VocabularyUploadResponse> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("name", data.name);
    formData.append("file", data.file);

    const xhr = new XMLHttpRequest();
    xhr.timeout = 600_000; // 10 minutes

    xhr.addEventListener("timeout", () => {
      reject(new Error("Upload timed out — please check your connection and try again"));
    });

    // Track upload progress
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        const percentComplete = (e.loaded / e.total) * 100;
        onProgress(percentComplete);
      }
    });

    // Handle completion
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText);
          resolve(response);
        } catch {
          reject(new Error("Failed to parse response"));
        }
      } else {
        try {
          const error = JSON.parse(xhr.responseText);
          reject(new Error(error.detail || `HTTP ${xhr.status}`));
        } catch {
          reject(new Error(`Upload failed: HTTP ${xhr.status}`));
        }
      }
    });

    // Handle errors
    xhr.addEventListener("error", () => {
      reject(new Error("Network error during upload"));
    });

    xhr.addEventListener("abort", () => {
      reject(new Error("Upload cancelled"));
    });

    // Open connection and set headers
    xhr.open("POST", `${API_BASE_URL}/vocabularies/`);

    const token = getToken();
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }

    // Send request
    xhr.send(formData);
  });
}

export async function deleteVocabulary(id: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/vocabularies/${id}`, {
    method: "DELETE",
  });
}

export async function downloadVocabulary(id: number): Promise<void> {
  const token = getToken();
  const headers: HeadersInit = {};

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/vocabularies/${id}/download`, {
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Download failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  // Get filename from Content-Disposition header or use default
  const contentDisposition = response.headers.get("Content-Disposition");
  const filenameMatch = contentDisposition?.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch ? filenameMatch[1] : `vocabulary_${id}.csv`;

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

export async function getVocabularyConcepts(vocabularyId: number, page = 1, limit = 50): Promise<ConceptsOutput> {
  return apiRequest<ConceptsOutput>(`/vocabularies/${vocabularyId}/concepts?page=${page}&limit=${limit}`);
}

export interface VocabularyConceptSearchParams {
  vocabularyId: number;
  query: string;
  page?: number;
  limit?: number;
  domain_id?: string;
  concept_class_id?: string;
  standard_concept?: string;
}

export async function searchVocabularyConcepts(params: VocabularyConceptSearchParams): Promise<ConceptsOutput> {
  const queryParams = new URLSearchParams({
    query: params.query,
    page: (params.page || 1).toString(),
    limit: (params.limit || 50).toString(),
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

  return apiRequest<ConceptsOutput>(`/vocabularies/${params.vocabularyId}/concepts/search?${queryParams.toString()}`);
}

export async function getDistinctDomains(vocabularyIds?: number[]): Promise<DistinctValuesOutput> {
  const params = vocabularyIds?.length ? `?vocabulary_ids=${vocabularyIds.join(",")}` : "";
  return apiRequest<DistinctValuesOutput>(`/vocabularies/filters/domains${params}`);
}

export async function getDistinctConceptClasses(vocabularyIds?: number[]): Promise<DistinctValuesOutput> {
  const params = vocabularyIds?.length ? `?vocabulary_ids=${vocabularyIds.join(",")}` : "";
  return apiRequest<DistinctValuesOutput>(`/vocabularies/filters/concept-classes${params}`);
}
