import { useState, useEffect, useCallback, useRef } from "react";
import type { SourceTerm, Dataset } from "@/types";
import {
  getRecordSourceTerms,
  extractRecordTerms as extractRecordTermsAPI,
  extractDatasetTerms as extractDatasetTermsAPI,
  getDatasetExtractionStatus as getDatasetExtractionStatusAPI,
  getActiveExtractionJob as getActiveExtractionJobAPI,
  cancelDatasetExtraction as cancelDatasetExtractionAPI,
  deleteDatasetExtractedTerms as deleteDatasetExtractedTermsAPI,
} from "@/api";

interface ExtractionProgress {
  completed: number;
  total: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
}

interface UseExtractionPollingParams {
  datasetId: number;
  dataset: Dataset | null;
  selectedRecordId: number | null;
  setSelectedRecordTerms: React.Dispatch<React.SetStateAction<SourceTerm[]>>;
  fetchStats: () => Promise<void>;
  refreshRecords: () => Promise<void>;
}

export function useExtractionPolling({
  datasetId,
  dataset,
  selectedRecordId,
  setSelectedRecordTerms,
  fetchStats,
  refreshRecords,
}: UseExtractionPollingParams) {
  const [isExtracting, setIsExtracting] = useState(false);
  const [isExtractingDataset, setIsExtractingDataset] = useState(false);
  const [isCancellingExtraction, setIsCancellingExtraction] = useState(false);
  const [extractionJobId, setExtractionJobId] = useState<string | null>(null);
  const [extractionProgress, setExtractionProgress] = useState<ExtractionProgress | null>(null);

  const cancelledRef = useRef(false);
  const latestSelectedRecordIdRef = useRef<number | null>(null);
  const extractionStorageKey = `extractionJob-${datasetId}`;
  const pollJobRef = useRef<((id: string) => Promise<{ status: string }>) | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  useEffect(() => {
    latestSelectedRecordIdRef.current = selectedRecordId;
  }, [selectedRecordId]);

  const pollExtractionJob = useCallback(
    async (jobId: string) => {
      setIsExtractingDataset(true);
      setExtractionJobId(jobId);
      localStorage.setItem(extractionStorageKey, jobId);

      try {
        let pollCount = 0;
        let lastStatus: ExtractionProgress["status"] = "pending";
        while (!cancelledRef.current) {
          const status = await getDatasetExtractionStatusAPI(datasetId, jobId);

          if (cancelledRef.current) break;

          lastStatus = status.status;
          setExtractionProgress({
            completed: status.completed,
            total: status.total,
            status: status.status,
          });

          if (["completed", "cancelled"].includes(status.status)) {
            break;
          }
          if (status.status === "failed") {
            throw new Error(status.error_message || "Dataset extraction failed");
          }

          pollCount++;
          if (pollCount % 5 === 0) {
            await refreshRecords();
          }

          await new Promise((res) => setTimeout(res, 2000));
        }

        const activeRecordId = latestSelectedRecordIdRef.current;
        if (!cancelledRef.current && activeRecordId) {
          const termsResponse = await getRecordSourceTerms(datasetId, activeRecordId);
          if (cancelledRef.current || latestSelectedRecordIdRef.current !== activeRecordId) {
            return { status: lastStatus };
          }
          setSelectedRecordTerms(termsResponse.source_terms);
        }
        if (!cancelledRef.current) {
          await refreshRecords();
          await fetchStats();
        }

        return { status: lastStatus };
      } finally {
        // Only clean up state and localStorage when the component is still mounted.
        // If cancelledRef.current is true the component unmounted (navigation) — keep
        // localStorage so the job can be resumed when the user comes back.
        if (!cancelledRef.current) {
          setIsExtractingDataset(false);
          setIsCancellingExtraction(false);
          setExtractionJobId(null);
          setExtractionProgress(null);
          localStorage.removeItem(extractionStorageKey);
        }
      }
    },
    [datasetId, selectedRecordId, setSelectedRecordTerms, fetchStats, refreshRecords, extractionStorageKey]
  );

  const extractTermsForRecord = useCallback(async () => {
    if (!selectedRecordId) {
      throw new Error("No record selected");
    }
    if (!dataset?.labels || dataset.labels.length === 0) {
      throw new Error("No labels defined for this dataset");
    }

    setIsExtracting(true);
    try {
      const response = await extractRecordTermsAPI(datasetId, selectedRecordId, dataset.labels);
      const termsResponse = await getRecordSourceTerms(datasetId, selectedRecordId);
      setSelectedRecordTerms(termsResponse.source_terms);
      await refreshRecords();
      await fetchStats();
      return response;
    } finally {
      setIsExtracting(false);
    }
  }, [datasetId, selectedRecordId, dataset, setSelectedRecordTerms, fetchStats, refreshRecords]);

  const extractTermsForDataset = useCallback(async () => {
    if (!dataset?.labels || dataset.labels.length === 0) {
      throw new Error("No labels defined for this dataset");
    }

    setExtractionProgress({ completed: 0, total: 0, status: "pending" });
    try {
      const { job_id } = await extractDatasetTermsAPI(datasetId, dataset.labels);
      if (!job_id) throw new Error("Extraction job did not return an ID");
      return await pollExtractionJob(job_id);
    } catch (err) {
      if (err instanceof Error && err.message.includes("already running")) {
        const active = await getActiveExtractionJobAPI(datasetId);
        if (active?.job_id) {
          return await pollExtractionJob(String(active.job_id));
        }
      }
      throw err;
    }
  }, [datasetId, dataset, pollExtractionJob]);

  const cancelDatasetExtraction = useCallback(async () => {
    if (!extractionJobId) return;
    setIsCancellingExtraction(true);
    try {
      await cancelDatasetExtractionAPI(datasetId, extractionJobId);
    } catch (err) {
      setIsCancellingExtraction(false);
      throw err;
    }
  }, [datasetId, extractionJobId]);

  const deleteExtractedTermsForDataset = useCallback(async () => {
    const res = await deleteDatasetExtractedTermsAPI(datasetId);
    await refreshRecords();
    await fetchStats();
    if (selectedRecordId) {
      const termsResponse = await getRecordSourceTerms(datasetId, selectedRecordId);
      setSelectedRecordTerms(termsResponse.source_terms);
    }
    return res;
  }, [datasetId, selectedRecordId, setSelectedRecordTerms, fetchStats, refreshRecords]);

  // Keep ref in sync so the mount-only effect always calls the latest version
  useEffect(() => {
    pollJobRef.current = pollExtractionJob;
  });

  // Resume polling once on mount if a job was active when the user navigated away.
  // Using an empty dep array is intentional — we only want this to fire on mount.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const savedJobId = localStorage.getItem(extractionStorageKey);
    if (savedJobId && pollJobRef.current) {
      pollJobRef.current(savedJobId).catch(() => {});
    }
  }, []);

  return {
    isExtracting,
    isExtractingDataset,
    isCancellingExtraction,
    extractionJobId,
    extractionProgress,
    extractTermsForRecord,
    extractTermsForDataset,
    cancelDatasetExtraction,
    deleteExtractedTermsForDataset,
  };
}
