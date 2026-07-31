import { useState, useEffect, useCallback, useRef } from "react";
import type { Dataset, DatasetCreate, PaginationMetadata } from "@/types";
import { getDatasets, createDataset, deleteDataset, downloadDataset as downloadDatasetAPI } from "@/api";

// ================================================
// Hook
// ================================================

const POLL_INTERVAL_MS = 3000;

function hasActiveProcessing(items: Dataset[]): boolean {
  return items.some((d) => d.status === "PENDING" || d.status === "PROCESSING");
}

export function useDatasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [pagination, setPagination] = useState<PaginationMetadata | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDatasets = useCallback(async (page = 1, limit = 50) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getDatasets(page, limit);
      setDatasets(response.datasets);
      setPagination(response.pagination);
      setIsProcessing(hasActiveProcessing(response.datasets));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch datasets");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const silentRefresh = useCallback(async () => {
    try {
      const response = await getDatasets(1, 50);
      setDatasets(response.datasets);
      setPagination(response.pagination);
      setIsProcessing(hasActiveProcessing(response.datasets));
    } catch {
      // Silent — don't set error or loading state
    }
  }, []);

  const uploadDataset = useCallback(
    async (data: DatasetCreate, onProgress?: (progress: number) => void) => {
      await createDataset(data, onProgress);
      await fetchDatasets();
    },
    [fetchDatasets]
  );

  const removeDataset = useCallback(
    async (id: number) => {
      await deleteDataset(id);
      await fetchDatasets();
    },
    [fetchDatasets]
  );

  const downloadDataset = useCallback(async (id: number) => {
    await downloadDatasetAPI(id);
  }, []);

  // Fetch on mount
  useEffect(() => {
    fetchDatasets();
  }, [fetchDatasets]);

  // Poll while processing
  useEffect(() => {
    if (isProcessing) {
      pollRef.current = setInterval(silentRefresh, POLL_INTERVAL_MS);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [isProcessing, silentRefresh]);

  return {
    datasets,
    pagination,
    isLoading,
    error,
    isProcessing,
    fetchDatasets,
    uploadDataset,
    removeDataset,
    downloadDataset,
  };
}
