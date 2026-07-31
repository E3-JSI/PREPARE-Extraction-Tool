import { useState, useEffect, useCallback, useRef } from "react";
import {
  startClusterAll as startClusterAllAPI,
  getClusterAllStatus as getClusterAllStatusAPI,
  getActiveClusterJob as getActiveClusterJobAPI,
  cancelClusterJob as cancelClusterJobAPI,
} from "@/api";
import type { ClusterJobStatusResponse } from "@/types";

export interface ClusterAllProgress {
  completed: number;
  total: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  clustered_labels: string[];
  skipped_labels: string[];
}

/**
 * Drives the dataset-wide "cluster all labels" background job: start, poll
 * progress (in labels), cancel, and resume an in-flight job on remount. Shared
 * by the Clustering page and the Overview page so both entry points hit the same
 * backend job. ``startClusterAll`` resolves with the final job status so callers
 * can toast the clustered/skipped summary.
 */
export function useClusterAllJob(datasetId: number) {
  const [isRunning, setIsRunning] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<ClusterAllProgress | null>(null);

  const cancelledRef = useRef(false);
  const storageKey = `clusterAllJob-${datasetId}`;
  const pollRef = useRef<((id: string) => Promise<ClusterJobStatusResponse | null>) | null>(null);

  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const poll = useCallback(
    async (id: string): Promise<ClusterJobStatusResponse | null> => {
      setIsRunning(true);
      setJobId(id);
      localStorage.setItem(storageKey, id);

      let last: ClusterJobStatusResponse | null = null;
      try {
        while (!cancelledRef.current) {
          const s = await getClusterAllStatusAPI(datasetId, id);
          if (cancelledRef.current) break;
          last = s;

          setProgress({
            completed: s.completed,
            total: s.total,
            status: s.status,
            clustered_labels: s.clustered_labels,
            skipped_labels: s.skipped_labels,
          });

          if (["completed", "cancelled"].includes(s.status)) break;
          if (s.status === "failed") throw new Error(s.error_message || "Clustering failed");

          await new Promise((res) => setTimeout(res, 2000));
        }
        return last;
      } finally {
        // Keep localStorage when the component unmounted (navigation) so the job
        // can be resumed on remount; only clear when still mounted.
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

  const startClusterAll = useCallback(async (): Promise<ClusterJobStatusResponse | null> => {
    try {
      const { job_id } = await startClusterAllAPI(datasetId);
      if (!job_id) throw new Error("No job ID returned");
      setProgress({ completed: 0, total: 0, status: "pending", clustered_labels: [], skipped_labels: [] });
      return await poll(String(job_id));
    } catch (err) {
      if (err instanceof Error && err.message.includes("already running")) {
        const active = await getActiveClusterJobAPI(datasetId);
        if (active?.job_id) {
          return await poll(String(active.job_id));
        }
      }
      throw err;
    }
  }, [datasetId, poll]);

  const cancelClusterAll = useCallback(async () => {
    if (!jobId) return;
    setIsCancelling(true);
    try {
      await cancelClusterJobAPI(datasetId, jobId);
    } catch (err) {
      setIsCancelling(false);
      throw err;
    }
  }, [datasetId, jobId]);

  // Keep ref current so the mount effect always calls the latest version.
  useEffect(() => {
    pollRef.current = poll;
  });

  // On mount: resume from localStorage first, then the backend active-job endpoint.
  useEffect(() => {
    const resume = async () => {
      const savedId = localStorage.getItem(storageKey);
      if (savedId) {
        pollRef.current?.(savedId).catch(() => localStorage.removeItem(storageKey));
        return;
      }
      try {
        const active = await getActiveClusterJobAPI(datasetId);
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

  return { isRunning, isCancelling, jobId, progress, startClusterAll, cancelClusterAll };
}
