import { useState, useEffect, useCallback, useRef } from "react";
import {
  startAutoMapAll as startAutoMapAllAPI,
  getAutoMapAllStatus as getAutoMapAllStatusAPI,
  getActiveAutoMapJob as getActiveAutoMapJobAPI,
  cancelAutoMapJob as cancelAutoMapJobAPI,
} from "@/api";
import type { AutoMapAllRequest } from "@/types";

export interface AutoMapJobProgress {
  completed: number;
  total: number;
  mapped_count: number;
  failed_count: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
}

/**
 * Drives the "Auto-Map All" background job: start → poll → completion, with a
 * Cancel action and localStorage resume so the progress bar reappears if the
 * user navigates away and back mid-run. Modeled on useDatasetExtractionJob.
 *
 * `onComplete` fires once when a job reaches a terminal state (completed or
 * cancelled) — for both an explicit start and a resumed job — so the page can
 * toast the final counts and refetch mappings in either case.
 */
export function useAutoMapJob(datasetId: number, onComplete?: (progress: AutoMapJobProgress) => void) {
  const [isRunning, setIsRunning] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<AutoMapJobProgress | null>(null);

  const cancelledRef = useRef(false);
  const storageKey = `autoMapJob-${datasetId}`;
  const pollRef = useRef<((id: string) => Promise<void>) | null>(null);
  const onCompleteRef = useRef(onComplete);

  // Keep the completion callback current without re-subscribing the poll loop.
  useEffect(() => {
    onCompleteRef.current = onComplete;
  });

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

      let finalProgress: AutoMapJobProgress | null = null;
      try {
        while (!cancelledRef.current) {
          const s = await getAutoMapAllStatusAPI(datasetId, id);
          if (cancelledRef.current) break;

          const p: AutoMapJobProgress = {
            completed: s.completed,
            total: s.total,
            mapped_count: s.mapped_count,
            failed_count: s.failed_count,
            status: s.status,
          };
          setProgress(p);

          if (["completed", "cancelled"].includes(s.status)) {
            finalProgress = p;
            break;
          }
          if (s.status === "failed") throw new Error(s.error_message || "Auto-mapping failed");

          await new Promise((res) => setTimeout(res, 2000));
        }

        if (!cancelledRef.current && finalProgress) onCompleteRef.current?.(finalProgress);
      } finally {
        // Only reset state when still mounted. On unmount (navigation) keep
        // localStorage so the job resumes when the user returns.
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

  const startAutoMap = useCallback(
    async (request: AutoMapAllRequest) => {
      try {
        setProgress({ completed: 0, total: 0, mapped_count: 0, failed_count: 0, status: "pending" });
        const { job_id } = await startAutoMapAllAPI(datasetId, request);
        if (!job_id) throw new Error("No job ID returned");
        await poll(String(job_id));
      } catch (err) {
        if (err instanceof Error && err.message.includes("already running")) {
          const active = await getActiveAutoMapJobAPI(datasetId);
          if (active?.job_id) {
            await poll(String(active.job_id));
            return;
          }
        }
        if (!cancelledRef.current) setProgress(null);
        throw err;
      }
    },
    [datasetId, poll]
  );

  const cancelAutoMap = useCallback(async () => {
    if (!jobId) return;
    setIsCancelling(true);
    try {
      await cancelAutoMapJobAPI(datasetId, jobId);
    } catch (err) {
      setIsCancelling(false);
      throw err;
    }
  }, [datasetId, jobId]);

  // Keep ref current so the mount effect always calls the latest version.
  useEffect(() => {
    pollRef.current = poll;
  });

  // On mount: check localStorage first, then fall back to the backend active-job endpoint.
  useEffect(() => {
    const resume = async () => {
      const savedId = localStorage.getItem(storageKey);
      if (savedId) {
        pollRef.current?.(savedId).catch(() => localStorage.removeItem(storageKey));
        return;
      }
      try {
        const active = await getActiveAutoMapJobAPI(datasetId);
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

  return { isRunning, isCancelling, jobId, progress, startAutoMap, cancelAutoMap };
}
