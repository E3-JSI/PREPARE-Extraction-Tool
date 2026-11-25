import { useEffect, useMemo, useState } from "react";
import classNames from "classnames";

import { getLatestValidationSet, getModels } from "@api/monitoring";
import Button from "@components/Button";
import Card from "@components/Card";
import ProgressBar from "@components/ProgressBar";
import Select from "@components/Select";
import StatCard from "@components/StatCard";
import type { ModelSummary, ValidationSetSummary } from "types";

import LabelSelector from "../../LabelSelector";
import TrainingLossChart from "../../charts/TrainingLossChart";
import { useMonitor } from "../../hooks/useMonitor";
import styles from "./styles.module.css";

// Curated metadata for the predefined baselines. `params` is the model's
// parameter count; `vramGB` is an approximate peak GPU VRAM to fine-tune at the
// default batch size (8). gliner_large ships only a pytorch checkpoint (no
// safetensors param count) so its count is approximate.
const GLINER_BASELINES = [
  {
    value: "urchade/gliner_multi-v2.1",
    label: "Multilingual (default)",
    params: "289M",
    vramGB: 8,
    description: "Multilingual general-purpose NER. A solid default for most datasets.",
  },
  {
    value: "urchade/gliner_large-v2.1",
    label: "Large (best, slower)",
    params: "~440M",
    vramGB: 12,
    description: "Highest accuracy, but heavier and slower to train. English-focused.",
  },
  {
    value: "E3-JSI/gliner-multi-med-ner-synthetic-v1",
    label: "Biomedical / clinical (multilingual)",
    params: "289M",
    vramGB: 8,
    description: "Biomedical / clinical NER across 9 languages, including Slovenian.",
  },
] as const;

// Compact one-line label for the dropdown: "Multilingual (default) · 289M · ~8 GB VRAM".
const formatBaselineLabel = (b: (typeof GLINER_BASELINES)[number]) => `${b.label} · ${b.params} · ~${b.vramGB} GB VRAM`;

const HF_BASELINE_OPTIONS = GLINER_BASELINES.map((b) => ({ value: b.value, label: formatBaselineLabel(b) }));

const VRAM_TOOLTIP =
  "Approximate peak GPU VRAM to fine-tune at the default batch size (8). Actual usage varies with batch size and sequence length.";

const SPLIT_OPTIONS = [
  { value: "0", label: "100 / 0 (no validation)" },
  { value: "0.1", label: "90 / 10" },
  { value: "0.2", label: "80 / 20" },
  { value: "0.3", label: "70 / 30" },
];
const SAVED_VALIDATION_SET_VALUE = "__saved_validation_set__";
const HELD_OUT_SPLIT_VALUE = "__held_out_split__";

// Pre-training → training phases surfaced in the progress stepper, in order.
// The `phase` values match the backend derivation and the MonitorProvider WS
// mapping ("loading" → "baseline" → "init" → "training").
const PHASE_STEPS = [
  { phase: "loading", short: "Load", label: "Loading model & preparing data" },
  { phase: "baseline", short: "Baseline", label: "Evaluating baseline model" },
  { phase: "init", short: "Init", label: "Initializing trainer" },
  { phase: "training", short: "Train", label: "Training" },
] as const;

// Copy for the amber notice shown while the run is in a pre-training phase.
const PRE_TRAINING_NOTICE =
  "Pre-training steps (model loading, baseline evaluation, trainer setup) can take 1–2 minutes on CPU. " +
  "This is normal — please don't stop the run.";

/**
 * Training view — trains a new model on one or more selected datasets: dataset
 * pickers (training + optional evaluation), aggregated stats and label
 * selection, train/eval split, base model selection, advanced hyperparameters,
 * start/stop, and live training progression (progress bar + loss curve).
 */
const TrainingView = () => {
  const {
    datasets,
    trainingStats,
    trainingDatasetIds,
    setTrainingDatasetIds,
    evalDatasetIds,
    setEvalDatasetIds,
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
    isTraining,
    progress,
    currentStep,
    totalSteps,
    trainingMetrics,
    trainingPhase,
    startTraining,
    stopTraining,
  } = useMonitor();

  // Index of the active phase in PHASE_STEPS (-1 when no run is in flight).
  const activePhaseIndex = PHASE_STEPS.findIndex((s) => s.phase === trainingPhase);
  const inPreTraining = trainingPhase != null && trainingPhase !== "training";

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [recommendedValidationSet, setRecommendedValidationSet] =
    useState<ValidationSetSummary | null>(null);
  const [selectedValidationSetId, setSelectedValidationSetId] =
    useState<number | null>(null);
  const [showValidationOptions, setShowValidationOptions] =
    useState(false);
  const [isValidationSetLoading, setIsValidationSetLoading] =
    useState(false);
  const [validationSetLookupFailed, setValidationSetLookupFailed] =
    useState(false);
  const [validationSetRefreshKey, setValidationSetRefreshKey] =
    useState(0);

  const resolvedModel = (
    useCustomModel ? customModel : baseModel
  ).trim();

  useEffect(() => {
    const normalizedModel = resolvedModel.trim();
    let cancelled = false;

    setRecommendedValidationSet(null);
    setSelectedValidationSetId(null);
    setEvalDatasetIds([]);
    setShowValidationOptions(false);
    setValidationSetLookupFailed(false);

    if (!normalizedModel) {
      setIsValidationSetLoading(false);
      setShowValidationOptions(true);
      return;
    }

    setIsValidationSetLoading(true);

    const timeoutId = window.setTimeout(() => {
      getLatestValidationSet(normalizedModel)
        .then((validationSet) => {
          if (cancelled) return;

          setRecommendedValidationSet(validationSet);
          setSelectedValidationSetId(
            validationSet?.validation_set_id ?? null
          );
          setShowValidationOptions(validationSet === null);
        })
        .catch(() => {
          if (cancelled) return;

          setRecommendedValidationSet(null);
          setSelectedValidationSetId(null);
          setValidationSetLookupFailed(true);
          setShowValidationOptions(false);
        })
        .finally(() => {
          if (!cancelled) {
            setIsValidationSetLoading(false);
          }
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [
    resolvedModel,
    setEvalDatasetIds,
    validationSetRefreshKey,
  ]);

  // Locally-available GLiNER models (discovered + trained) usable as a base
  // model. Only gliner-engine local folders are valid GLiNER training bases.
  const [localModels, setLocalModels] = useState<ModelSummary[]>([]);
  useEffect(() => {
    getModels()
      .then((list) => setLocalModels(list.filter((m) => m.engine === "gliner" && m.path)))
      .catch(() => setLocalModels([]));
  }, []);

  const baseModelOptions = useMemo(
    () => [
      ...localModels.map((m) => ({ value: m.path as string, label: `${m.name} · local` })),
      ...HF_BASELINE_OPTIONS,
      { value: "custom", label: "Custom…" },
    ],
    [localModels]
  );

  const selectedBaseline = GLINER_BASELINES.find((b) => b.value === baseModel);

  const datasetOptions = datasets.map((d) => ({
    value: String(d.id),
    label: d.name,
  }));

  // Eval datasets are distinct from training datasets.
  const evalOptions = datasetOptions.filter(
    (option) => !trainingDatasetIds.includes(Number(option.value))
  );

  const hasEvalDatasets = evalDatasetIds.length > 0;
  const usingSavedValidationSet = selectedValidationSetId !== null;

  const validationOptions = [
    ...(recommendedValidationSet
      ? [
          {
            value: SAVED_VALIDATION_SET_VALUE,
            label: `Saved validation set · ${recommendedValidationSet.record_count.toLocaleString()} documents`,
          },
        ]
      : []),
    {
      value: HELD_OUT_SPLIT_VALUE,
      label: "Held-out split of training data",
    },
    ...evalOptions,
  ];

  const validationValues = usingSavedValidationSet
    ? [SAVED_VALIDATION_SET_VALUE]
    : hasEvalDatasets
      ? evalDatasetIds.map(String)
      : [HELD_OUT_SPLIT_VALUE];

  const handleValidationValuesChange = (values: string[]) => {
    const addedValue = values.find(
      (value) => !validationValues.includes(value)
    );

    if (
      addedValue === SAVED_VALIDATION_SET_VALUE &&
      recommendedValidationSet
    ) {
      setSelectedValidationSetId(
        recommendedValidationSet.validation_set_id
      );
      setEvalDatasetIds([]);
      setShowValidationOptions(false);
      return;
    }

    if (addedValue === HELD_OUT_SPLIT_VALUE) {
      setSelectedValidationSetId(null);
      setEvalDatasetIds([]);
      return;
    }

    const datasetIds = values
      .filter(
        (value) =>
          value !== SAVED_VALIDATION_SET_VALUE &&
          value !== HELD_OUT_SPLIT_VALUE
      )
      .map(Number)
      .filter(Number.isInteger);

    setSelectedValidationSetId(null);
    setEvalDatasetIds(datasetIds);
  };

  const handleStartTraining = async () => {
    const started = await startTraining(selectedValidationSetId);

    if (started) {
      setValidationSetRefreshKey((key) => key + 1);
    }
  };

  return (
    <div className={styles.view}>
      {/* DATASETS */}
      <Card title="Training data">
        <div className={styles.dataGrid}>
          <div className={styles.field}>
            <p className={styles.field__label}>Training datasets</p>
            <Select
              multiSelect
              values={trainingDatasetIds.map(String)}
              onValuesChange={(vals) => {
                const nextTrainingDatasetIds = vals.map(Number);

                setTrainingDatasetIds(nextTrainingDatasetIds);
                setEvalDatasetIds(
                  evalDatasetIds.filter(
                    (datasetId) => !nextTrainingDatasetIds.includes(datasetId)
                  )
                );
              }}
              options={datasetOptions}
              placeholder="Select datasets…"
            />
          </div>

          <div className={styles.field}>
            <p className={styles.field__label}>
              Evaluation datasets (optional)
            </p>

            {isValidationSetLoading ? (
              <p className={styles.hint}>
                Checking for a saved validation set...
              </p>
            ) : validationSetLookupFailed ? (
              <div className={styles.validationSummary}>
                <p className={styles.warning} role="alert">
                  Could not load the saved validation set.
                </p>
                <Button
                  variant="ghost"
                  size="small"
                  onClick={() =>
                    setValidationSetRefreshKey((key) => key + 1)
                  }
                >
                  Retry
                </Button>
              </div>
            ) : recommendedValidationSet &&
              usingSavedValidationSet &&
              !showValidationOptions ? (
              <div className={styles.validationSummary}>
                <div>
                  <p className={styles.validationSummary__title}>
                    ✓ Saved validation set ·{" "}
                    {recommendedValidationSet.record_count.toLocaleString()}{" "}
                    documents
                  </p>
                  <p className={styles.hint}>
                    Reusing this set keeps learning-curve results comparable.
                  </p>
                </div>

                <Button
                  variant="ghost"
                  size="small"
                  onClick={() => setShowValidationOptions(true)}
                >
                  Change
                </Button>
              </div>
            ) : (
              <>
                <Select
                  multiSelect
                  values={validationValues}
                  onValuesChange={handleValidationValuesChange}
                  options={validationOptions}
                  placeholder="Choose validation data..."
                />

                <p className={styles.hint}>
                  {usingSavedValidationSet
                    ? "Using the saved validation set."
                    : hasEvalDatasets
                      ? "Evaluating on the selected datasets."
                      : "A held-out split of the training data will be used."}
                </p>
              </>
            )}
          </div>
        </div>
      </Card>

      {/* STATS + LABELS */}
      {trainingStats &&
        (() => {
          const excluded = trainingStats.totalRecords - trainingStats.reviewedRecords;
          const allReviewed = excluded <= 0;
          return (
            <Card title="Labels & statistics">
              <div className={styles.stats}>
                <StatCard
                  label="Records (used for training)"
                  value={trainingStats.reviewedRecords}
                  subtext={`of ${trainingStats.totalRecords.toLocaleString()} in dataset`}
                />
                <StatCard
                  label="Terms (used for training)"
                  value={trainingStats.reviewedTerms}
                  subtext={`of ${trainingStats.totalTerms.toLocaleString()} in dataset`}
                />
              </div>

              <p
                className={classNames(styles.reviewCallout, {
                  [styles["reviewCallout--warn"]]: !allReviewed,
                  [styles["reviewCallout--ok"]]: allReviewed,
                })}
                role="note"
              >
                {allReviewed
                  ? `All ${trainingStats.totalRecords.toLocaleString()} records reviewed — the full dataset will be used.`
                  : `Only reviewed records are used for training and evaluation. ${excluded.toLocaleString()} of ${trainingStats.totalRecords.toLocaleString()} records are not yet reviewed and will be excluded.`}
              </p>

              <LabelSelector datasetStats={trainingStats} onChange={setSelectedLabels} />
            </Card>
          );
        })()}

      {/* TRAINING CONFIG */}
      <Card title="Training configuration">
        <div className={styles.configGrid}>
          <div className={styles.configGrid__main}>
            {/* Model selector */}
            <div className={styles.field}>
              <label className={styles.field__label} htmlFor="base-model-select">
                Base model
              </label>

              <Select
                id="base-model-select"
                value={useCustomModel ? "custom" : baseModel}
                onValueChange={(v) => {
                  if (v === "custom") {
                    setUseCustomModel(true);
                  } else {
                    setUseCustomModel(false);
                    setBaseModel(v);
                  }
                }}
                options={baseModelOptions}
                fullWidth={false}
              />

              {useCustomModel ? (
                <>
                  <input
                    id="custom-model-input"
                    type="text"
                    value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    placeholder="e.g. urchade/gliner_medium-v2.1 or /model/gliner/my-model"
                    className={styles.input}
                    style={{ marginTop: "var(--space-2)" }}
                  />
                  <p className={styles.warning} role="alert">
                    ⚠ Advanced: custom base models must be GLiNER-compatible. An incompatible model will fail to train.
                  </p>
                </>
              ) : (
                selectedBaseline && (
                  <div className={styles.modelInfo}>
                    <p className={styles.modelInfo__desc}>{selectedBaseline.description}</p>
                    <dl className={styles.modelInfo__specs}>
                      <div className={styles.modelInfo__spec}>
                        <dt className={styles.modelInfo__term}>Model</dt>
                        <dd className={styles.modelInfo__value}>
                          <code className={styles.code}>{selectedBaseline.value}</code>
                        </dd>
                      </div>
                      <div className={styles.modelInfo__spec}>
                        <dt className={styles.modelInfo__term}>Parameters</dt>
                        <dd className={styles.modelInfo__value}>{selectedBaseline.params}</dd>
                      </div>
                      <div className={styles.modelInfo__spec}>
                        <dt className={styles.modelInfo__term}>Training VRAM</dt>
                        <dd className={styles.modelInfo__value} title={VRAM_TOOLTIP}>
                          ~{selectedBaseline.vramGB} GB
                        </dd>
                      </div>
                    </dl>
                  </div>
                )
              )}
            </div>
          </div>

          <div className={styles.runPanel}>
            {/* Train / Eval split */}
            <div className={styles.field}>
              <p className={styles.field__label}>Train / Eval split</p>

              <Select
                value={String(valSplitRatio)}
                onValueChange={(v) => setValSplitRatio(Number(v))}
                fullWidth={false}
                options={SPLIT_OPTIONS}
                disabled={
                  usingSavedValidationSet ||
                  hasEvalDatasets ||
                  isValidationSetLoading ||
                  validationSetLookupFailed
                }
              />
              {usingSavedValidationSet ? (
                <p className={styles.hint}>
                  Disabled while the saved validation set is selected.
                </p>
              ) : hasEvalDatasets ? (
                <p className={styles.hint}>
                  Ignored while evaluation datasets are selected.
                </p>
              ) : null}
            </div>

            {/* Advanced hyperparameters */}
            <div className={styles.field}>
              <button
                type="button"
                className={styles["advanced-toggle"]}
                onClick={() => setShowAdvanced((s) => !s)}
                aria-expanded={showAdvanced}
              >
                {showAdvanced ? "▾" : "▸"} Advanced (hyperparameters)
              </button>

              {showAdvanced && (
                <div className={styles.hyperparams}>
                  <label className={styles.hyperparam}>
                    <span className={styles.hyperparam__label}>Epochs</span>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={numEpochs}
                      onChange={(e) => setNumEpochs(Math.max(1, Math.round(Number(e.target.value) || 1)))}
                      className={styles.input}
                    />
                  </label>

                  <label className={styles.hyperparam}>
                    <span className={styles.hyperparam__label}>Learning rate</span>
                    <input
                      type="number"
                      min={0}
                      step="0.000001"
                      value={learningRate}
                      onChange={(e) => setLearningRate(Number(e.target.value))}
                      className={styles.input}
                    />
                  </label>

                  <label className={styles.hyperparam}>
                    <span className={styles.hyperparam__label}>Batch size</span>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={trainBatchSize}
                      onChange={(e) => setTrainBatchSize(Math.max(1, Math.round(Number(e.target.value) || 1)))}
                      className={styles.input}
                    />
                  </label>
                </div>
              )}
            </div>

            {/* Actions */}
            <div className={styles.actions}>
              <Button
                variant="primary"
                onClick={handleStartTraining}
                disabled={
                  isTraining ||
                  trainingDatasetIds.length === 0 ||
                  isValidationSetLoading ||
                  validationSetLookupFailed ||
                  !resolvedModel
                }
              >
                Start
              </Button>
              <Button variant="danger" onClick={stopTraining} disabled={!isTraining}>
                Stop
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {/* LIVE TRAINING PROGRESSION */}
      <Card title="Training progress">
        {activePhaseIndex >= 0 && (
          <ol className={styles.stepper} aria-label="Training phase">
            {PHASE_STEPS.map((step, i) => {
              const state = i < activePhaseIndex ? "done" : i === activePhaseIndex ? "active" : "pending";
              return (
                <li
                  key={step.phase}
                  className={classNames(styles.step, styles[`step--${state}`])}
                  aria-current={state === "active" ? "step" : undefined}
                >
                  <span className={styles.step__marker}>{state === "done" ? "✓" : i + 1}</span>
                  {step.short}
                </li>
              );
            })}
          </ol>
        )}

        {activePhaseIndex >= 0 && <p className={styles.phaseCaption}>{PHASE_STEPS[activePhaseIndex].label}</p>}

        {inPreTraining && (
          <p className={classNames(styles.reviewCallout, styles["reviewCallout--warn"])} role="status">
            {PRE_TRAINING_NOTICE}
          </p>
        )}

        <div className={styles.progress}>
          <ProgressBar value={progress} />
          {(isTraining || currentStep > 0) && (
            <p className={styles.progressLabel}>
              Step {currentStep} / {totalSteps} ({progress}%)
            </p>
          )}
        </div>

        <TrainingLossChart metrics={trainingMetrics} isTraining={isTraining} />
      </Card>
    </div>
  );
};

export default TrainingView;