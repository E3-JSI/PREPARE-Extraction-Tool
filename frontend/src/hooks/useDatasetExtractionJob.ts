import { useState, useEffect, useCallback, useRef } from "react";
import {
  extractDatasetTerms as extractDatasetTermsAPI,
  getDatasetExtractionStatus as getDatasetExtractionStatusAPI,
  getActiveExtractionJob as getActiveExtractionJobAPI,
  cancelDatasetExtraction as cancelDatasetExtractionAPI,
} from "@/api";

export interface ExtractionJobProgress {
  completed: number;
  total: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
}

export function useDatasetExtractionJob(datasetId: number) {
  const [isRunning, setIsRunning] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<ExtractionJobProgress | null>(null);

  const cancelledRef = useRef(false);
  const storageKey = `extractionJob-${datasetId}`;
  const pollRef = useRef<((id: string) => Promise<void>) | null>(null);

  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const poll = useCallback(
    async (id: string) => {
      setIsRunning(true);
      setJobId(id);
      localStorage.setItem(storageKey, id);

      try {
        while (!cancelledRef.current) {
          const s = await getDatasetExtractionStatusAPI(datasetId, id);
          if (cancelledRef.current) break;

          setProgress({ completed: s.completed, total: s.total, status: s.status });

          if (["completed", "cancelled"].includes(s.status)) break;
          if (s.status === "failed") throw new Error(s.error_message || "Extraction failed");

          await new Promise((res) => setTimeout(res, 2000));
        }
      } finally {
        if (!cancelledRef.current) {
          setIsRunning(false);
          setIsCancelling(false);
          setJobId(null);
          setProgress(null);
          localStorage.removeItem(storageKey);
        }
      }
    },
    [datasetId, storageKey]
  );

  const startExtraction = useCallback(
    async (labels: string[]) => {
      try {
        const { job_id } = await extractDatasetTermsAPI(datasetId, labels);
        if (!job_id) throw new Error("No job ID returned");
        setProgress({ completed: 0, total: 0, status: "pending" });
        await poll(String(job_id));
      } catch (err) {
        if (err instanceof Error && err.message.includes("already running")) {
          const active = await getActiveExtractionJobAPI(datasetId);
          if (active?.job_id) {
            await poll(String(active.job_id));
            return;
          }
        }
        throw err;
      }
    },
    [datasetId, poll]
  );

  const cancelExtraction = useCallback(async () => {
    if (!jobId) return;
    setIsCancelling(true);
    try {
      await cancelDatasetExtractionAPI(datasetId, jobId);
    } catch (err) {
      setIsCancelling(false);
      throw err;
    }
  }, [datasetId, jobId]);

  // Keep ref current so the mount effect always calls the latest version
  useEffect(() => {
    pollRef.current = poll;
  });

  // On mount: check localStorage first, then fall back to the backend active-job endpoint
  useEffect(() => {
    const resume = async () => {
      const savedId = localStorage.getItem(storageKey);
      if (savedId) {
        pollRef.current?.(savedId).catch(() => localStorage.removeItem(storageKey));
        return;
      }
      try {
        const active = await getActiveExtractionJobAPI(datasetId);
        if (active?.job_id) {
          pollRef.current?.(String(active.job_id)).catch(() => {});
        }
      } catch {
        // Non-critical — no active job to resume
      }
    };
    resume();
    // Mount-only: datasetId/storageKey are read once to resume an in-flight job.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { isRunning, isCancelling, jobId, progress, startExtraction, cancelExtraction };
}
