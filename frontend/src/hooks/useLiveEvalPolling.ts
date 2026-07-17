import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelLiveEval as cancelLiveEvalAPI,
  getLiveEvalStatus as getLiveEvalStatusAPI,
  startLiveEval as startLiveEvalAPI,
} from "@api/liveEval";
import type { LiveEvalMetrics } from "types";

type LiveEvalStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

interface LiveEvalProgress {
  completed: number;
  total: number;
  status: LiveEvalStatus;
}

/**
 * Drives a live-eval job for a single model: start, 2s-poll, cancel, and resume
 * on remount. Cloned from `useExtractionPolling` — the localStorage key is keyed
 * by model id so navigating away and back rehydrates the in-flight job and its
 * progress bar; the final metrics are surfaced once the job completes.
 */
export function useLiveEvalPolling(modelId: number | null) {
  const [isRunning, setIsRunning] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [progress, setProgress] = useState<LiveEvalProgress | null>(null);
  const [metrics, setMetrics] = useState<LiveEvalMetrics | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);
  const storageKey = modelId != null ? `liveEvalJob-${modelId}` : null;
  const pollJobRef = useRef<((id: number) => Promise<void>) | null>(null);

  // Track mount state so an unmount (navigation) keeps localStorage for resume.
  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const pollLiveEvalJob = useCallback(
    async (id: number) => {
      if (!storageKey) return;
      setIsRunning(true);
      setJobId(id);
      setMetrics(null);
      setMessage(null);
      setError(null);
      localStorage.setItem(storageKey, String(id));

      try {
        while (!cancelledRef.current) {
          const status = await getLiveEvalStatusAPI(id);
          if (cancelledRef.current) break;

          setProgress({
            completed: status.completed,
            total: status.total,
            status: status.status,
          });

          if (status.status === "completed") {
            setMetrics(status.metrics ?? null);
            setMessage(status.metrics?.message ?? null);
            break;
          }
          if (status.status === "cancelled") {
            break;
          }
          if (status.status === "failed") {
            setError(status.error_message || "Live evaluation failed");
            break;
          }

          await new Promise((res) => setTimeout(res, 2000));
        }
      } finally {
        // Only tear down when still mounted. On unmount keep localStorage so the
        // job resumes when the user returns to this model.
        if (!cancelledRef.current) {
          setIsRunning(false);
          setIsCancelling(false);
          setJobId(null);
          if (storageKey) localStorage.removeItem(storageKey);
        }
      }
    },
    [storageKey]
  );

  const runLiveEval = useCallback(
    async (datasetId: number) => {
      if (modelId == null) throw new Error("No model selected");
      setProgress({ completed: 0, total: 0, status: "pending" });
      setMetrics(null);
      setMessage(null);
      setError(null);
      const res = await startLiveEvalAPI(modelId, datasetId);
      if (res.status === "completed") {
        // Short-circuit (e.g. no held-out records): fetch the final metrics.
        const status = await getLiveEvalStatusAPI(res.job_id);
        setProgress({ completed: status.completed, total: status.total, status: status.status });
        setMetrics(status.metrics ?? null);
        setMessage(status.metrics?.message ?? res.message ?? null);
        return;
      }
      await pollLiveEvalJob(res.job_id);
    },
    [modelId, pollLiveEvalJob]
  );

  const cancelLiveEval = useCallback(async () => {
    if (jobId == null) return;
    setIsCancelling(true);
    try {
      await cancelLiveEvalAPI(jobId);
    } catch (err) {
      setIsCancelling(false);
      throw err;
    }
  }, [jobId]);

  // Keep the ref pointing at the latest poll fn for the mount-only resume effect.
  useEffect(() => {
    pollJobRef.current = pollLiveEvalJob;
  });

  // Resume once on mount / model change if a job was active when navigating away.
  useEffect(() => {
    if (!storageKey) return;
    const saved = localStorage.getItem(storageKey);
    if (saved && pollJobRef.current) {
      pollJobRef.current(Number(saved)).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId]);

  return {
    isRunning,
    isCancelling,
    progress,
    metrics,
    message,
    error,
    runLiveEval,
    cancelLiveEval,
  };
}
