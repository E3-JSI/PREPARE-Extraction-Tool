import { useState, useEffect, useRef } from "react";
import Layout from "@components/Layout";
import Button from "@components/Button";
import StatCard from "@components/StatCard";
import { usePageTitle } from "@hooks/usePageTitle";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  BarChart,
  Bar,
} from "recharts";

import LabelSelector from "./LabelSelector";

// ------------------ UI WRAPPER ------------------

const SectionCard = ({ title, children }: any) => (
  <div
    style={{
      background: "#fff",
      padding: 16,
      borderRadius: 12,
      boxShadow: "0 2px 8px rgba(0,0,0,0.05)",
      marginBottom: 20,
    }}
  >
    <h2 style={{ marginBottom: 12 }}>{title}</h2>
    {children}
  </div>
);

// ------------------ TYPES ------------------

const DEFAULT_MODEL = "urchade/gliner_small-v2.1";

type Run = { run_id: number };

type PerLabelMetrics = {
  f1: number;
  precision: number;
  recall: number;
};

type EvaluationResponse = {
  run_id: number;
  per_label: Record<string, PerLabelMetrics>;
};

interface Dataset {
  id: number;
  name: string;
}

interface TrainingMetric {
  epoch: number;
  loss: number;
}

// ------------------ COMPONENT ------------------

const Monitor = () => {
  usePageTitle("Monitor");

  const token = localStorage.getItem("access_token");

  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<number | null>(null);
  const [allRunEvaluations, setAllRunEvaluations] = useState<any[]>([]);

  const [datasetStats, setDatasetStats] = useState<any>(null);

  const [, setRuns] = useState<Run[]>([]);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);

  const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);

  const [trainingMetrics, setTrainingMetrics] = useState<TrainingMetric[]>([]);
  const [isTraining, setIsTraining] = useState(false);
  const [trainingStatus, setTrainingStatus] = useState<string>("");

  const [selectedLabels, setSelectedLabels] = useState<string[]>([]);

  // Model selection
  const [baseModel, setBaseModel] = useState<string>(DEFAULT_MODEL);
  const [customModel, setCustomModel] = useState<string>("");
  const [useCustomModel, setUseCustomModel] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);

  // ------------------ RESET ------------------

  const resetAll = () => {
    setRuns([]);
    setSelectedRun(null);
    setEvaluation(null);
    setTrainingMetrics([]);
    setIsTraining(false);
    setTrainingStatus("");
    setSelectedLabels([]);
  };

  // ------------------ DATASETS ------------------

  useEffect(() => {
    const fetchDatasets = async () => {
      const res = await fetch("http://localhost:8000/api/v1/datasets", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setDatasets(data.datasets || []);
    };

    fetchDatasets();
  }, [token]);

  const selectDataset = async (id: number) => {
    setSelectedDatasetId(id);
    resetAll();

    const res = await fetch(
      `http://localhost:8000/api/v1/monitoring/datasets/${id}/full-stats`,
      { headers: { Authorization: `Bearer ${token}` } }
    );

    const data = await res.json();
    setDatasetStats(data);
  };

  // ------------------ RUNS ------------------

  useEffect(() => {
    if (!selectedDatasetId) return;

    const fetchRuns = async () => {
      const res = await fetch(
        `http://localhost:8000/api/v1/monitoring/datasets/${selectedDatasetId}/runs`,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      const data = await res.json();
      setRuns(data || []);
      setSelectedRun(data?.[0]?.run_id ?? null);
    };

    fetchRuns();
  }, [selectedDatasetId]);

  // ------------------ ALL RUN EVAL ------------------

  useEffect(() => {
    if (!selectedDatasetId) return;

    const fetchAll = async () => {
      const res = await fetch(
        `http://localhost:8000/api/v1/monitoring/datasets/${selectedDatasetId}/runs/evaluations`,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      const data = await res.json();
      setAllRunEvaluations(data ?? []);
    };

    fetchAll();
  }, [selectedDatasetId]);

  // ------------------ SINGLE EVAL ------------------

  useEffect(() => {
    if (!selectedRun) return;

    const fetchEvaluation = async () => {
      const res = await fetch(
        `http://localhost:8000/api/v1/monitoring/runs/${selectedRun}/evaluation`,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      const data = await res.json();
      setEvaluation(data);
    };

    fetchEvaluation();
  }, [selectedRun]);

  // ------------------ NORMALIZATION ------------------

  const normalizeLabel = (label: string) =>
    label.normalize("NFD").replace(/[̀-ͯ]/g, "");

  const normalizedRuns = allRunEvaluations.map((run) => ({
    run_id: run.run_id,
    per_label: run.evaluations?.[0]?.per_label ?? {},
  }));

  const labelKeys = Array.from(
    new Set(
      normalizedRuns.flatMap((r) => Object.keys(r.per_label ?? {}))
    )
  )
    .map(normalizeLabel)
    .filter((l) => !["micro avg", "macro avg", "weighted avg"].includes(l));

  const comparisonLineData = normalizedRuns.map((run) => {
    const row: any = { run: run.run_id };

    const normalizedPerLabel: any = {};
    Object.entries(run.per_label).forEach(([k, v]) => {
      normalizedPerLabel[normalizeLabel(k)] = v;
    });

    labelKeys.forEach((label) => {
      row[label] = normalizedPerLabel[label]?.["f1-score"] ?? 0;
    });

    return row;
  });

  // ------------------ WEBSOCKET ------------------

  useEffect(() => {
    if (!selectedDatasetId) return;

    const ws = new WebSocket(
      `ws://localhost:8000/api/v1/monitoring/ws/training?token=${token}`
    );

    wsRef.current = ws;

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "epoch_update") {
        setTrainingMetrics((prev) => [
          ...prev,
          {
            epoch: data.epoch ?? prev.length + 1,
            loss: data.loss ?? data.train_loss ?? 0,
          },
        ]);
      }

      if (data.type === "training_start" || data.type === "training_info") {
        setIsTraining(true);
        setTrainingStatus("Training started…");
      }

      if (data.type === "completed") {
        setIsTraining(false);
        setTrainingStatus(`Completed — model saved to: ${data.output_path ?? "unknown"}`);
      }

      if (data.type === "stopped") {
        setIsTraining(false);
        setTrainingStatus("Training stopped.");
      }

      if (data.type === "error") {
        setIsTraining(false);
        setTrainingStatus(`Error: ${data.message}`);
      }
    };

    return () => ws.close();
  }, [selectedDatasetId]);

  // ------------------ TRAINING ------------------

  const resolvedModel = useCustomModel ? customModel.trim() : baseModel;

  const startTraining = async () => {
    if (!resolvedModel) {
      setTrainingStatus("Please enter a model name.");
      return;
    }

    setTrainingMetrics([]);
    setIsTraining(true);
    setTrainingStatus("Submitting…");

    const res = await fetch("http://localhost:8000/api/v1/monitoring/start", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        dataset_id: selectedDatasetId,
        labels: selectedLabels,
        base_model: resolvedModel,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setIsTraining(false);
      setTrainingStatus(`Failed to start: ${err.detail ?? res.statusText}`);
    }
  };

  const stopTraining = async () => {
    await fetch("http://localhost:8000/api/v1/monitoring/stop", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });

    setIsTraining(false);
    setTrainingStatus("Stop requested.");
  };

  // ------------------ CHART DATA ------------------

  const chartData = evaluation?.per_label
    ? Object.entries(evaluation.per_label)
        .filter(([k]) => !["micro avg", "macro avg", "weighted avg"].includes(k))
        .map(([label, m]: any) => ({
          labelName: label,
          precision: m.precision,
          recall: m.recall,
          f1: m["f1-score"],
        }))
    : [];

  const COLORS = ["#8884d8", "#82ca9d", "#ff7300", "#0088fe"];

  // ------------------ RENDER ------------------

  return (
    <Layout>
      <h1 style={{ fontSize: 26, fontWeight: 700 }}>
        Monitoring Dashboard
      </h1>

      {/* DATASET */}
      <SectionCard title="Dataset">
        {datasets.map((d) => (
          <Button
            key={d.id}
            onClick={() => selectDataset(d.id)}
            variant={selectedDatasetId === d.id ? "primary" : "outline"}
          >
            {d.name}
          </Button>
        ))}
      </SectionCard>

      {/* STATS */}
      {datasetStats && (
        <SectionCard title={`Dataset ${selectedDatasetId}`}>
          <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
            <StatCard label="Records" value={datasetStats.totalRecords} />
            <StatCard label="Terms" value={datasetStats.totalTerms} />
          </div>

          <LabelSelector
            datasetId={selectedDatasetId}
            datasetStats={datasetStats}
            onChange={setSelectedLabels}
          />
        </SectionCard>
      )}

      {/* TRAINING */}
      <SectionCard title="Training">
        {/* Model selector */}
        <div style={{ marginBottom: 16 }}>
          <p style={{ marginBottom: 8, fontWeight: 600 }}>Base model</p>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="radio"
                checked={!useCustomModel}
                onChange={() => setUseCustomModel(false)}
              />
              <span>
                Default:{" "}
                <code style={{ background: "#f5f5f5", padding: "2px 6px", borderRadius: 4 }}>
                  {DEFAULT_MODEL}
                </code>
              </span>
            </label>

            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="radio"
                checked={useCustomModel}
                onChange={() => setUseCustomModel(true)}
              />
              Custom model path or HuggingFace ID
            </label>

            {useCustomModel && (
              <input
                type="text"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder="e.g. urchade/gliner_medium-v2.1 or /model/gliner/my-model"
                style={{
                  padding: "8px 12px",
                  borderRadius: 8,
                  border: "1px solid #ccc",
                  fontSize: 14,
                  width: "100%",
                  maxWidth: 480,
                }}
              />
            )}
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Button onClick={startTraining} disabled={isTraining}>Start</Button>
          <Button onClick={stopTraining} disabled={!isTraining}>Stop</Button>
        </div>

        {trainingStatus && (
          <p style={{ marginTop: 10, color: isTraining ? "green" : "#555" }}>
            {trainingStatus}
          </p>
        )}
      </SectionCard>

      {/* GRID CHARTS */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>

        {/* TRAINING PROGRESS */}
        <SectionCard title="Training Progress">
          {trainingMetrics.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={trainingMetrics}>
                <XAxis dataKey="epoch" />
                <YAxis />
                <Tooltip />
                <Line dataKey="loss" stroke="#ff4d4f" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p>No training data</p>
          )}
        </SectionCard>

        {/* PER LABEL */}
        <SectionCard title="Per-label Evaluation">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={chartData}>
                <XAxis dataKey="labelName" />
                <YAxis domain={[0, 1]} />
                <Tooltip />
                <Legend />
                <Bar dataKey="precision" />
                <Bar dataKey="recall" />
                <Bar dataKey="f1" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p>No evaluation data</p>
          )}
        </SectionCard>
      </div>

      {/* RUN COMPARISON */}
      <SectionCard title="Run Comparison (F1 across runs)">
        {comparisonLineData.length > 0 ? (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={comparisonLineData}>
              <XAxis dataKey="run" />
              <YAxis domain={[0, 1]} />
              <Tooltip />
              <Legend />

              {labelKeys.map((label, i) => (
                <Line
                  key={label}
                  dataKey={label}
                  stroke={COLORS[i % COLORS.length]}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p>No comparison data</p>
        )}
      </SectionCard>
    </Layout>
  );
};

export default Monitor;
