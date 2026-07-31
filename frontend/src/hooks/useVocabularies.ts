import { useState, useEffect, useCallback, useRef } from "react";
import type { Vocabulary, VocabularyCreate, PaginationMetadata } from "@/types";
import {
  getVocabularies,
  createVocabulary,
  deleteVocabulary,
  downloadVocabulary as downloadVocabularyAPI,
} from "@/api";

// ================================================
// Hook
// ================================================

const POLL_INTERVAL_MS = 3000;

function hasActiveProcessing(items: Vocabulary[]): boolean {
  return items.some((v) => v.status === "PENDING" || v.status === "PROCESSING");
}

export function useVocabularies() {
  const [vocabularies, setVocabularies] = useState<Vocabulary[]>([]);
  const [pagination, setPagination] = useState<PaginationMetadata | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchVocabularies = useCallback(async (page = 1, limit = 50) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getVocabularies(page, limit);
      setVocabularies(response.vocabularies);
      setPagination(response.pagination);
      setIsProcessing(hasActiveProcessing(response.vocabularies));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch vocabularies");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const silentRefresh = useCallback(async () => {
    try {
      const response = await getVocabularies(1, 50);
      setVocabularies(response.vocabularies);
      setPagination(response.pagination);
      setIsProcessing(hasActiveProcessing(response.vocabularies));
    } catch {
      // Silent — don't set error or loading state
    }
  }, []);

  const addVocabulary = useCallback(
    async (data: VocabularyCreate, onProgress?: (progress: number) => void) => {
      await createVocabulary(data, onProgress);
      await fetchVocabularies();
    },
    [fetchVocabularies]
  );

  const removeVocabulary = useCallback(
    async (id: number) => {
      await deleteVocabulary(id);
      await fetchVocabularies();
    },
    [fetchVocabularies]
  );

  const downloadVocabulary = useCallback(async (id: number) => {
    await downloadVocabularyAPI(id);
  }, []);

  // Fetch on mount
  useEffect(() => {
    fetchVocabularies();
  }, [fetchVocabularies]);

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
    vocabularies,
    pagination,
    isLoading,
    error,
    isProcessing,
    fetchVocabularies,
    addVocabulary,
    removeVocabulary,
    downloadVocabulary,
  };
}
