import type {
  DatasetsOutput,
  DatasetOutput,
  DatasetUploadResponse,
  DatasetCreate,
  DatasetStats,
  DatasetOverviewOutput,
  MessageOutput,
} from "types";

import { apiRequest, getToken, API_BASE_URL } from "./client";

export async function getDatasets(page = 1, limit = 50): Promise<DatasetsOutput> {
  return apiRequest<DatasetsOutput>(`/datasets/?page=${page}&limit=${limit}`);
}

export async function getDataset(id: number): Promise<DatasetOutput> {
  return apiRequest<DatasetOutput>(`/datasets/${id}`);
}

export async function createDataset(
  data: DatasetCreate,
  onProgress?: (progress: number) => void
): Promise<DatasetUploadResponse> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("name", data.name);
    formData.append("labels", data.labels);
    formData.append("file", data.file);
    if (data.date_label) {
      formData.append("date_label", data.date_label);
    }
    if (data.label_relations) {
      formData.append("label_relations", data.label_relations);
    }

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
    xhr.open("POST", `${API_BASE_URL}/datasets/`);

    const token = getToken();
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }

    // Send request
    xhr.send(formData);
  });
}

export async function deleteDataset(id: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${id}`, {
    method: "DELETE",
  });
}

export async function deleteDatasetExtractedTerms(datasetId: number): Promise<MessageOutput> {
  return apiRequest<MessageOutput>(`/datasets/${datasetId}/source-terms`, {
    method: "DELETE",
  });
}

export async function downloadDataset(id: number, format: "csv" | "json" | "gliner" = "csv"): Promise<void> {
  const token = getToken();
  const headers: HeadersInit = {};

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/datasets/${id}/download?format=${format}`, { headers });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Download failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  // Get filename from Content-Disposition header or use default
  const contentDisposition = response.headers.get("Content-Disposition");
  const filenameMatch = contentDisposition?.match(/filename="?([^"]+)"?/);
  const fallbackExtension = format === "csv" ? "csv" : "json";
  const filename = filenameMatch ? filenameMatch[1] : `dataset_${id}.${fallbackExtension}`;

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

export async function getDatasetStats(datasetId: number): Promise<DatasetStats> {
  return apiRequest<DatasetStats>(`/datasets/${datasetId}/statistics`);
}

export async function getDatasetOverview(datasetId: number): Promise<DatasetOverviewOutput> {
  return apiRequest<DatasetOverviewOutput>(`/datasets/${datasetId}/overview`);
}
