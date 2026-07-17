import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@hooks/useAuth";
import { useToastApi } from "@hooks/useToast";
import { ApiError } from "@api/client";
import {
  getActiveRun,
  getDatasets,
  getMultiDatasetStats,
  getTrainingWSUrl,
  startTraining as apiStartTraining,
  stopTraining as apiStopTraining,
} from "@api/monitoring";
import type { MonitorDataset, MonitorDatasetStats, TrainingMetric } from "types";

import { DEFAULT_MODEL, MonitorContext } from "../hooks/useMonitor";
import type { MonitorContextValue, MonitorView } from "../hooks/useMonitor";

/**
 * Map a failed `startTraining` request to an actionable toast payload.
 *
 * A 409 from the backend carries a machine-readable code: the trainer slot is
 * held by a genuinely-active run (`TRAINING_BUSY`) or by a previous run that is
 * still winding down after a stop (`TRAINING_STOPPING`, worth retrying). Anything
 * else falls back to the error's own message.
 */
const describeStartError = (err: unknown): { message: string; suggestion?: string } => {
  if (err instanceof ApiError && err.status === 409) {
    const code = (err.detail as { error?: string } | null | undefined)?.error;
    if (code === "TRAINING_STOPPING") {
      return {
        message: "Previous run is still stopping",
        suggestion: "Try again in a moment.",
      };
    }
    if (code === "TRAINING_BUSY") {
      return { message: "Another training run is already active." };
    }
  }
  return { message: err instanceof Error ? err.message : String(err) };
};

/** Provides all Monitor state + actions to the page and its views. */
const MonitorProvider = ({ children }: { children: ReactNode }) => {
  // Stable imperative API — toast state lives in ToastProvider (above this
  // provider) so showing/dismissing a toast never rerenders Monitor consumers.
  const toast = useToastApi();

  const showAlert = (
    payload: { message?: string; detail?: string; suggestion?: string },
    type: "error" | "success" | "info" = "error"
  ) => {
    const base = payload?.message || payload?.detail || "Unknown error";
    const message = payload?.suggestion ? `${base} — ${payload.suggestion}` : base;
    toast.showToast(message, type);
  };

  // The provider is mounted above the router so its state + training websocket
  // survive page navigation. It reads the token reactively from the auth context
  // (not once at mount) so a login after mount connects the WS, and a logout
  // tears it down.
  const { isAuthenticated } = useAuth();
  const [token, setToken] = useState<string | null>(() =>
    isAuthenticated ? localStorage.getItem("access_token") : null
  );

  useEffect(() => {
    setToken(isAuthenticated ? localStorage.getItem("access_token") : null);
  }, [isAuthenticated]);

  const [activeView, setActiveView] = useState<MonitorView>("models");

  const [progress, setProgress] = useState(0);
  const [, setTotalEpochs] = useState(4);
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);

  const [datasets, setDatasets] = useState<MonitorDataset[]>([]);

  // Training datasets (multi-select) + optional eval datasets, with their
  // aggregated stats.
  const [trainingDatasetIds, setTrainingDatasetIds] = useState<number[]>([]);
  const [evalDatasetIds, setEvalDatasetIds] = useState<number[]>([]);
  const [trainingStats, setTrainingStats] = useState<MonitorDatasetStats | null>(null);

  const [valSplitRatio, setValSplitRatio] = useState<number>(0.1);

  // Hyperparameters (defaults match the bioner trainer's current values).
  const [numEpochs, setNumEpochs] = useState<number>(4);
  const [learningRate, setLearningRate] = useState<number>(5e-6);
  const [trainBatchSize, setTrainBatchSize] = useState<number>(8);

  const [trainingMetrics, setTrainingMetrics] = useState<TrainingMetric[]>([]);
  const [isTraining, setIsTraining] = useState(false);
  // Live pre-training phase, derived from the WS event stream (and rehydrated
  // from the active-run endpoint on mount). Null while no run is in flight.
  const [trainingPhase, setTrainingPhase] = useState<string | null>(null);

  const [selectedLabels, setSelectedLabels] = useState<string[]>([]);

  // Model selection
  const [baseModel, setBaseModel] = useState<string>(DEFAULT_MODEL);
  const [customModel, setCustomModel] = useState<string>("");
  const [useCustomModel, setUseCustomModel] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isTrainingRef = useRef(false);
  const totalEpochsRef = useRef(4);
  const totalStepsRef = useRef(0);
  // When the last training WS event arrived — drives the stalled-run watchdog.
  const lastEventAtRef = useRef(Date.now());
  const [activeRunId, setActiveRunId] = useState<number | null>(null);

  // keep a ref of isTraining so the WS reconnect logic can read it without re-subscribing
  useEffect(() => {
    isTrainingRef.current = isTraining;
  }, [isTraining]);

  // Teardown + user alert for a failed run (error event or dead-run reconcile).
  const markRunDead = (message?: string | null, suggestion?: string) => {
    const msg = message ?? "Training stopped unexpectedly.";
    setIsTraining(false);
    setProgress(0);
    setCurrentStep(0);
    setTotalSteps(0);
    setTrainingPhase(null);
    showAlert({ message: msg, suggestion }, "error");
  };

  // ------------------ DATASETS ------------------

  useEffect(() => {
    if (!token) return;

    const fetchDatasets = async () => {
      try {
        const data = await getDatasets(1, 50);
        setDatasets(data.datasets ?? []);
      } catch (err) {
        console.error(err);
        setDatasets([]);
      }
    };

    fetchDatasets();
  }, [token]);

  // ------------------ TRAINING DATASET STATS (aggregated) ------------------

  useEffect(() => {
    if (!token || trainingDatasetIds.length === 0) {
      setTrainingStats(null);
      return;
    }

    let cancelled = false;
    getMultiDatasetStats(trainingDatasetIds)
      .then((data) => {
        if (!cancelled) setTrainingStats(data);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error(err);
        setTrainingStats(null);
      });

    return () => {
      cancelled = true;
    };
  }, [trainingDatasetIds, token]);

  // ------------------ WEBSOCKET ------------------

  // The training-event stream is global (events are broadcast for any run), so
  // it connects whenever the user is authenticated — not tied to a dataset.
  useEffect(() => {
    if (!token) return;
    let closed = false;

    const handleMessage = (event: MessageEvent) => {
      if (closed) return;

      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        console.error("Failed to parse training WS message:", e);
        return;
      }

      lastEventAtRef.current = Date.now();

      switch (data.type) {
        case "training_start":
          setIsTraining(true);
          setTrainingMetrics([]);
          setProgress(0);
          setCurrentStep(0);
          // Model is loaded; baseline evaluation runs next (the dominant CPU stall).
          setTrainingPhase("baseline");

          totalEpochsRef.current = data.num_epochs ?? 4;
          setTotalEpochs(data.num_epochs ?? 4);
          totalStepsRef.current = data.total_steps ?? 0;
          setTotalSteps(data.total_steps ?? 0);
          break;

        case "training_info":
          setIsTraining(true);
          toast.info(`Training started (${data.train_size} samples)`);
          // First event of the run: model is loading and data is being prepared.
          setTrainingPhase("loading");
          break;

        case "baseline_evaluation_completed":
          // Baseline eval done; the trainer is initializing before step 1.
          setTrainingPhase("init");
          break;

        case "epoch_update": {
          const epoch = Number(data.epoch ?? 0);

          // The epoch counter ends below num_epochs under gradient
          // accumulation — only ever move the bar forward.
          setProgress((prev) => {
            const safeTotal = totalEpochsRef.current;
            if (safeTotal <= 0) return prev;
            return Math.max(prev, Math.min(100, (epoch / safeTotal) * 100));
          });

          break;
        }

        case "train_log": {
          // Plot points that carry a train loss OR an eval loss. Eval rows arrive
          // on their own train_log (eval_loss, no train loss) and must be kept so
          // the eval curve renders; only metric-less logs (learning_rate / grad_norm
          // only) are skipped, since those would inject a spurious empty point.
          const loss = data.loss != null && Number.isFinite(Number(data.loss)) ? Number(data.loss) : null;
          const evalLoss =
            data.eval_loss != null && Number.isFinite(Number(data.eval_loss)) ? Number(data.eval_loss) : null;
          if (loss == null && evalLoss == null) break;

          const epoch = Number(data.epoch ?? 0);
          const step = data.step != null ? Number(data.step) : null;

          if (step != null) {
            setCurrentStep(step);
            // First real training step: pre-training phases are over.
            if (step > 0) setTrainingPhase("training");
            const total = totalStepsRef.current;
            if (total > 0) {
              setProgress(Math.min(100, Math.round((step / total) * 100)));
            }
          }

          setTrainingMetrics((prev) => [...prev, { epoch, loss, step, eval_loss: evalLoss }]);
          break;
        }

        case "completed":
          setIsTraining(false);
          toast.success(`Training completed — saved to ${data.output_path ?? "unknown"}`);
          setProgress(100);
          setCurrentStep(0);
          setTotalSteps(0);
          setTrainingPhase(null);
          break;

        case "stopped":
          setIsTraining(false);
          toast.info("Training stopped.");
          setProgress(0);
          setCurrentStep(0);
          setTotalSteps(0);
          setTrainingPhase(null);
          break;

        case "error":
          markRunDead(data.message, data.suggestion);
          break;
      }
    };

    const scheduleReconnect = () => {
      if (closed) return;
      // exponential backoff: 1s, 2s, 4s … capped at 30s
      const attempt = reconnectAttemptsRef.current;
      const delay = Math.min(30000, 1000 * 2 ** attempt);
      reconnectAttemptsRef.current = attempt + 1;
      // Only surface the transient state if a training run is actually in
      // flight, and only on the first attempt — later retries would re-toast
      // the same condition on every backoff tick.
      if (isTrainingRef.current && attempt === 0) {
        toast.warning("Connection lost — reconnecting…");
      }
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(getTrainingWSUrl(token));
      wsRef.current = ws;

      ws.onopen = () => {
        // successful connection — reset the backoff
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = handleMessage;

      ws.onclose = () => {
        // ignore the close triggered by intentional teardown (cleanup sets closed)
        if (closed) return;
        scheduleReconnect();
      };

      // onerror is followed by onclose in browsers; let onclose drive the reconnect
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      reconnectAttemptsRef.current = 0;
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // ------------------ REHYDRATE IN-FLIGHT RUN ------------------

  // On mount / (re)login, fetch any in-flight run and restore its progress so a
  // run that started (or advanced, or finished) while this page was unmounted —
  // or before a full page reload — is shown immediately, without waiting for the
  // next websocket event and without the user having to reselect the dataset.
  // Live WS events append seamlessly afterwards (train_log carries the global
  // step, so currentStep stays authoritative).
  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    getActiveRun()
      .then((run) => {
        if (cancelled) return;
        if (!run) {
          // No run in flight — clear any stale phase from a prior run.
          setTrainingPhase(null);
          return;
        }

        if (run.status === "failed") {
          // Backend just reconciled the run as dead — surface the reason.
          markRunDead(run.error_message);
          return;
        }

        setActiveRunId(run.run_id);
        setIsTraining(true);
        setTrainingPhase(run.phase ?? null);
        // Drives the stats card + progress region without a manual reselect.
        setTrainingDatasetIds(run.dataset_ids);

        if (run.total_steps != null) {
          totalStepsRef.current = run.total_steps;
          setTotalSteps(run.total_steps);
        }
        if (run.num_epochs != null) {
          totalEpochsRef.current = run.num_epochs;
          setTotalEpochs(run.num_epochs);
        }
        if (run.current_step != null) {
          setCurrentStep(run.current_step);
          if (run.total_steps && run.total_steps > 0) {
            setProgress(Math.min(100, Math.round((run.current_step / run.total_steps) * 100)));
          }
        }
        if (run.metrics?.length) {
          setTrainingMetrics(run.metrics);
        }
      })
      .catch((err) => {
        // Rehydration is best-effort: a failure must not crash the provider.
        console.error("Failed to rehydrate active training run:", err);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // ------------------ STALLED-RUN WATCHDOG ------------------

  // The trainer can die without a final event (e.g. OOM-killed worker). When
  // the WS goes quiet mid-run, ask the backend to verify the run with bioner.
  useEffect(() => {
    if (!token) return;
    const STALL_MS = 90_000;

    const timer = setInterval(() => {
      if (!isTrainingRef.current) return;
      if (Date.now() - lastEventAtRef.current < STALL_MS) return;
      // Back off until the next full quiet period before re-verifying.
      lastEventAtRef.current = Date.now();
      getActiveRun()
        .then((run) => {
          if (run?.status === "failed") markRunDead(run.error_message);
        })
        .catch(() => {
          // Best-effort; retried next quiet period.
        });
    }, 30_000);

    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // ------------------ TRAINING ------------------

  const resolvedModel = useCustomModel ? customModel.trim() : baseModel;

  const startTraining = async () => {
    if (trainingDatasetIds.length === 0) return;

    setTrainingMetrics([]);
    setIsTraining(true);

    try {
      const data = await apiStartTraining({
        dataset_ids: trainingDatasetIds,
        eval_dataset_ids: evalDatasetIds,
        labels: selectedLabels,
        base_model: resolvedModel,
        val_ratio: valSplitRatio,
        num_epochs: numEpochs,
        learning_rate: learningRate,
        train_batch_size: trainBatchSize,
      });

      setActiveRunId(data.run_id);
    } catch (err) {
      setIsTraining(false);
      showAlert(describeStartError(err), "error");
    }
  };

  const stopTraining = async () => {
    if (!activeRunId || !token) return;

    await apiStopTraining(activeRunId);

    setIsTraining(false);
    toast.info("Stop requested.");
  };

  const value: MonitorContextValue = {
    activeView,
    setActiveView,

    datasets,
    trainingStats,

    isTraining,
    progress,
    currentStep,
    totalSteps,
    trainingMetrics,
    trainingPhase,

    trainingDatasetIds,
    setTrainingDatasetIds,
    evalDatasetIds,
    setEvalDatasetIds,
    selectedLabels,
    setSelectedLabels,
    valSplitRatio,
    setValSplitRatio,
    baseModel,
    setBaseModel,
    customModel,
    setCustomModel,
    useCustomModel,
    setUseCustomModel,

    numEpochs,
    setNumEpochs,
    learningRate,
    setLearningRate,
    trainBatchSize,
    setTrainBatchSize,

    startTraining,
    stopTraining,

    toast,
  };

  return <MonitorContext.Provider value={value}>{children}</MonitorContext.Provider>;
};

export default MonitorProvider;
