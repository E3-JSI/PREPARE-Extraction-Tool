import { apiRequest } from "./client";

/* ---------------- TYPES ---------------- */

export interface ModelOption {
  id: number;
  name: string;
  path: string;
  created_at?: string;
  type?: string;
  engine?: string;
}

/* ---------------- MODELS ---------------- */

export function getAvailableModels() {
  return apiRequest<{ models: ModelOption[] }>(
    `/bioner/models/available`
  );
}

export function getCurrentModel(token: string) {
  return apiRequest<{ model_path: string }>(
    `/bioner/models/current`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

export function selectModel(modelId: number, token: string) {
  return apiRequest<{ message?: string }>(
    `/bioner/models/select`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model_id: modelId,
      }),
    }
  );
}