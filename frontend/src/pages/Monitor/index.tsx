  import { useMemo, useState, useEffect, useRef } from "react";
  import Layout from "@components/Layout";
  import Button from "@components/Button";
  import StatCard from "@components/StatCard";
  import { usePageTitle } from "@/hooks/usePageTitle";


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

// ------------------ HEATMAP ------------------

/*const Heatmap = ({
  data,
  labels,
}: {
  data: any[];
  labels: string[];
}) => {
  const getColor = (value: number) => {
    // value between 0 and 1
    const intensity = Math.round(value * 255);

    return `rgb(
      ${255 - intensity},
      ${255 - intensity},
      255
    )`;
  };

  return (
    <div
      style={{
        overflowX: "auto",
        width: "100%",
      }}
    >
      <table
        style={{
          borderCollapse: "collapse",
          width: "100%",
          minWidth: 700,
        }}
      >
        <thead>
          <tr>
            <th
              style={{
                padding: 10,
                border: "1px solid #ddd",
                background: "#fafafa",
                position: "sticky",
                left: 0,
                zIndex: 2,
              }}
            >
              Run
            </th>

            {labels.map((label) => (
              <th
                key={label}
                style={{
                  padding: 10,
                  border: "1px solid #ddd",
                  background: "#fafafa",
                  textAlign: "center",
                }}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {data.map((row) => (
            <tr key={row.run}>
              <td
                style={{
                  padding: 10,
                  border: "1px solid #ddd",
                  fontWeight: 700,
                  background: "#fff",
                  position: "sticky",
                  left: 0,
                }}
              >
                #{row.run}
              </td>

              {labels.map((label) => {
                const value = Number(row[label] ?? 0);

                return (
                  <td
                    key={label}
                    title={`${label}: ${value.toFixed(4)}`}
                    style={{
                      padding: 14,
                      border: "1px solid #ddd",
                      textAlign: "center",
                      background: getColor(value),
                      transition: "0.2s",
                      fontWeight: 600,
                    }}
                  >
                    {value.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};*/


  const Monitor = () => {
    usePageTitle("Monitor");


    const [alert, setAlert] = useState<null | {
    type: "error" | "success" | "info";
    message: string;
    suggestion?: string;
  }>(null);


  const showAlert = (payload: any, type: "error" | "success" | "info" = "error") => {
    setAlert({
      type,
      message: payload?.message || payload?.detail || "Unknown error",
      suggestion: payload?.suggestion,
    });

    // auto-hide after 5 seconds (optional)
    setTimeout(() => setAlert(null), 5000);
  };

  
const [token, setToken] = useState<string | null>(null);

useEffect(() => {
  setToken(localStorage.getItem("access_token"));
}, []);


    const [progress, setProgress] = useState(0);
    const [, setTotalEpochs] = useState(4);

    const [datasets, setDatasets] = useState<Dataset[]>([]);
    const [selectedDatasetId, setSelectedDatasetId] = useState<number | null>(null);
    const [, setAllRunEvaluations] = useState<any[]>([]);
    const [evaluations, setEvaluations] = useState<any[]>([]);
    const [hovered, setHovered] = useState<any>(null);
    const [datasetStats, setDatasetStats] = useState<any>(null);

    const [runs, setRuns] = useState<Run[]>([]);
    const [selectedRun, setSelectedRun] = useState<number | null>(null);

    const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);

    const [trainingMetrics, setTrainingMetrics] = useState<TrainingMetric[]>([]);
    const [isTraining, setIsTraining] = useState(false);
    const [trainingStatus, setTrainingStatus] = useState<string>("");

    const [selectedLabels, setSelectedLabels] = useState<string[]>([]);
  

    // Model selection
    const [baseModel,] = useState<string>(DEFAULT_MODEL);
    const [customModel, setCustomModel] = useState<string>("");
    const [useCustomModel, setUseCustomModel] = useState(false);

    const wsRef = useRef<WebSocket | null>(null);
    const totalEpochsRef = useRef(4);
    const [activeRunId, setActiveRunId] = useState<number | null>(null);

    // ------------------ RESET ------------------

    const resetAll = () => {
      setRuns([]);
      setSelectedRun(null);
      setEvaluation(null);
      setTrainingMetrics([]);
      setIsTraining(false);
      setTrainingStatus("");
      setSelectedLabels([]);
      setAllRunEvaluations([]);
    };

    // ------------------ DATASETS ------------------

useEffect(() => {
  if (!token) {
    console.warn("No token yet — skipping dataset fetch");
    return;
  }

  const fetchDatasets = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/v1/datasets", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) {
        console.error("Dataset fetch failed:", res.status);
        return;
      }

      const data = await res.json();

      console.log("DATASETS RAW:", data);

      const datasetsArray = data?.datasets ?? [];

      console.log("DATASETS PARSED:", datasetsArray);

      setDatasets(datasetsArray);
    } catch (err) {
      console.error("Dataset fetch error:", err);
      setDatasets([]);
    }
  };

  fetchDatasets();
}, [token]);

    const selectDataset = async (id: number) => {
      setSelectedDatasetId(id);
      resetAll();

      const res = await fetch(
        `http://localhost:8000/api/v1/bioner/datasets/${id}/full-stats`,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      const data = await res.json();
      setDatasetStats(data);
    };

useEffect(() => {
  if (!selectedDatasetId || !token) return;

  const fetchAll = async () => {
    const res = await fetch(
      `http://localhost:8000/api/v1/bioner/evaluations`,
      { headers: { Authorization: `Bearer ${token}` } }
    );

    const data = await res.json();

    setEvaluations(Array.isArray(data) ? data : []);
  };

  fetchAll();
}, [selectedDatasetId, token]);


    // ------------------ RUNS ------------------

useEffect(() => {
  if (!selectedDatasetId || !token) return;

  const fetchRuns = async () => {
    try {
      const res = await fetch(
        `http://localhost:8000/api/v1/bioner/datasets/${selectedDatasetId}/runs`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      // 🔴 safety: handle non-JSON / backend errors
      const contentType = res.headers.get("content-type");
      const isJson = contentType?.includes("application/json");

      const raw = isJson ? await res.json() : await res.text();

      // 🔴 defensive parsing (handles all backend shapes)
      const runsArray = Array.isArray(raw)
        ? raw
        : raw?.runs
        ? raw.runs
        : raw?.data
        ? raw.data
        : [];

      console.log("✅ RUNS API RESPONSE:", raw);
      console.log("✅ NORMALIZED RUNS:", runsArray);

      setRuns(runsArray);

      // auto-select first run safely
      setSelectedRun(runsArray?.[0]?.run_id ?? null);
    } catch (error) {
      console.error("❌ Failed to fetch runs:", error);
      setRuns([]);
      setSelectedRun(null);
    }
  };

  fetchRuns();
}, [selectedDatasetId, token]);
    // ------------------ ALL RUN EVAL ------------------

    useEffect(() => {
      if (!selectedDatasetId) return;

      const fetchAll = async () => {
        const res = await fetch(
          `http://localhost:8000/api/v1/bioner/datasets/${selectedDatasetId}/runs/evaluations`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        const data = await res.json();
        setAllRunEvaluations(data ?? []);
      };

      fetchAll();
    }, [selectedDatasetId]);


  //const evaluatedRunIds = new Set(
  //  evaluatedRuns.map((r: any) => r.run_id)
  //);

    // ------------------ SINGLE EVAL ------------------

    useEffect(() => {
      if (!selectedRun) return;

      const fetchEvaluation = async () => {
        const res = await fetch(
          `http://localhost:8000/api/v1/bioner/runs/${selectedRun}/evaluation`,
          { headers: { Authorization: `Bearer ${token}` } }
        );

        const data = await res.json();
        setEvaluation(data);
      };

      fetchEvaluation();
    }, [selectedRun]);

 const [metricMode, setMetricMode] = useState<"f1" | "precision" | "recall">("f1");

    // ------------------ LABEL NORMALIZATION ------------------

const normalizeLabel = (label: string) =>
  label.normalize("NFD").replace(/[\u0300-\u036f]/g, "");

// ------------------ SAFE API DATA ------------------

const datasetEvaluations = evaluations.filter(
  (r: any) => r.dataset_id === selectedDatasetId
);

const safeRuns = datasetEvaluations
  ? evaluations
  : [];

// ------------------ METRIC MODE ------------------

 

// ------------------ ALL LABELS ------------------

const labelKeys = Array.from(
  new Set(
    safeRuns.flatMap((run: any) =>
      Object.keys(run?.per_label ?? {}).map(normalizeLabel)
    )
  )
).sort();



const heatmapData = useMemo(() => {
  return safeRuns.map((run: any) => {
    const row: any = {
      run: run.run_id,
      labels: {},
    };

    const perLabel = run.per_label ?? {};

    Object.entries(perLabel).forEach(([label, metrics]: any) => {
      const norm = normalizeLabel(label);

      row.labels[norm] = Number(
        metrics?.[metricMode] ?? 0
      );
    });

    // ensure all labels exist
    labelKeys.forEach((label) => {
      if (row.labels[label] === undefined) {
        row.labels[label] = 0;
      }
    });

    return row;
  });
}, [safeRuns, metricMode, labelKeys]);


const getColor = (value: number) => {
  // clamp 0–1
  const v = Math.max(0, Math.min(1, value));

  // red → yellow → green scale
  const r = v < 0.5 ? 255 : Math.floor(255 * (1 - v));
  const g = v < 0.5 ? Math.floor(255 * v * 2) : 255;
  const b = 120;

  return `rgb(${r},${g},${b})`;
};
 

    
    // ------------------ WEBSOCKET ------------------

    useEffect(() => {
      if (!selectedDatasetId) return;

      const ws = new WebSocket(
        `ws://localhost:8000/api/v1/bioner/ws/training?token=${token}`
      );

      wsRef.current = ws;

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
      case "training_start":
        setIsTraining(true);
        setTrainingMetrics([]);
        setProgress(0);
        setTrainingStatus("Training started…");

        totalEpochsRef.current = data.num_epochs ?? 4;
        setTotalEpochs(data.num_epochs ?? 4);
        break;

      case "training_info":
        setIsTraining(true);
        setTrainingStatus(
          `Training started (${data.train_size} samples)`
        );
        break;

      case "epoch_update": {
        const epoch = Number(data.epoch ?? 0);

        setProgress(() => {
          const safeTotal = totalEpochsRef.current;

          if (safeTotal <= 0) return 0;

          return Math.min(100, (epoch / safeTotal) * 100);
        });

        break;
      }

      case "train_log": {
        console.log("TRAIN LOG RECEIVED", data);

        const epoch = Number(data.epoch ?? 0);
        const loss = Number(data.loss ?? 0);

        console.log("epoch=", epoch, "loss=", loss);

        setTrainingMetrics((prev) => {
          const next = [...prev, { epoch, loss }];
          console.log("trainingMetrics=", next);
          return next;
        });

        break;
      }
    
      case "completed":
        setIsTraining(false);
        setTrainingStatus(
          `Completed — saved to ${data.output_path ?? "unknown"}`
        );
        break;

      case "stopped":
        setIsTraining(false);
        setTrainingStatus("Training stopped.");
        setProgress(0);
        break;

      case "error":
        setIsTraining(false);
        setTrainingStatus(`Error: ${data.message}`);

          showAlert(
            {
              message: data.message,
              suggestion: data.suggestion,
            },
            "error"
          );

        break;
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

      const res = await fetch(
        "http://localhost:8000/api/v1/bioner/training/start",
        {
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
        }
      );

      // ❌ ERROR HANDLING FIRST
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setIsTraining(false);
        setTrainingStatus("Training failed to start");
        showAlert(err, "error");
        return;
      }

      // ✅ SUCCESS PATH (ADD IT HERE)
      const data = await res.json();
      setActiveRunId(data.run_id);
      setTrainingStatus("Training started successfully");
  };

  const stopTraining = async () => {
    if (!activeRunId) return;

    await fetch(
      `http://localhost:8000/api/v1/bioner/training/stop/${activeRunId}`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }
    );

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

        {alert && (
          <div
            style={{
              position: "fixed",
              top: 20,
              right: 20,
              padding: 16,
              borderRadius: 10,
              background: alert.type === "error" ? "#ff4d4f" : "#52c41a",
              color: "white",
              maxWidth: 320,
              boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
              zIndex: 9999,
            }}
          >
            <div style={{ fontWeight: 700 }}>{alert.message}</div>

            {alert.suggestion && (
              <div style={{ marginTop: 6, fontSize: 12, opacity: 0.9 }}>
                💡 {alert.suggestion}
              </div>
            )}
          </div>
        )}

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
            <div style={{ marginTop: 10 }}>
            <div>Progress: {progress.toFixed(0)}%</div>
            <div style={{ height: 6, background: "#eee", borderRadius: 4 }}>
              <div
                style={{
                  width: `${progress}%`,
                  height: "100%",
                  background: "#4caf50",
                  borderRadius: 4,
                }}
              />
            </div>
          </div>

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

          <SectionCard title="Select Run">
            <select
              value={selectedRun ?? ""}
              onChange={(e) => setSelectedRun(Number(e.target.value))}
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  Run #{r.run_id}
                </option>
              ))}
            </select>

            <div style={{ marginTop: 8, fontSize: 13, opacity: 0.7 }}>
              Selected Run: {selectedRun ?? "None"}
            </div>
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

<SectionCard title="Run Comparison Heatmap (All Runs)">

  <div style={{ marginBottom: 10 }}>
    <label style={{ fontWeight: 600 }}>Metric: </label>
    <select
      value={metricMode}
      onChange={(e) =>
        setMetricMode(e.target.value as any)
      }
    >
      <option value="f1">F1</option>
      <option value="precision">Precision</option>
      <option value="recall">Recall</option>
    </select>
  </div>

  {heatmapData.length > 0 ? (
    <div style={{ overflowX: "auto" }}>
      <svg width={900} height={400}>
        {/* LABEL HEADERS */}
        {labelKeys.map((label, i) => (
          <text
            key={label}
            x={120 + i * 80}
            y={20}
            fontSize={12}
            textAnchor="middle"
          >
            {label}
          </text>
        ))}

        {/* ROWS */}
        {heatmapData.map((row, rowIndex) => (
          <g key={row.run}>
            {/* RUN LABEL */}
            <text
              x={10}
              y={60 + rowIndex * 40}
              fontSize={12}
            >
              Run {row.run}
            </text>

            {/* CELLS */}
            {labelKeys.map((label, colIndex) => {
              const value = row.labels[label];

              return (
                <rect
                  key={label}
                  x={120 + colIndex * 80}
                  y={40 + rowIndex * 40}
                  width={70}
                  height={30}
                  fill={getColor(value)}
                  stroke="#fff"
                  onMouseEnter={() =>
                    setHovered({
                      run: row.run,
                      label,
                      value,
                    })
                  }
                  onMouseLeave={() => setHovered(null)}
                />
              );
            })}
          </g>
        ))}
      </svg>

      {/* TOOLTIP */}
      {hovered && (
        <div
          style={{
            position: "fixed",
            left: 20,
            bottom: 20,
            padding: 10,
            background: "#111",
            color: "#fff",
            borderRadius: 8,
            fontSize: 13,
          }}
        >
          <div><b>Run:</b> {hovered.run}</div>
          <div><b>Label:</b> {hovered.label}</div>
          <div><b>Value:</b> {hovered.value.toFixed(3)}</div>
        </div>
      )}
    </div>
  ) : (
    <p>No data</p>
  )}
</SectionCard>
      </Layout>
    );
  };

  export default Monitor;
