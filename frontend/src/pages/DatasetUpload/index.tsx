import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "@components/Layout";
import FileDropzone from "@components/FileDropzone";
import Button from "@components/Button";
import ProgressBar from "@components/ProgressBar";
import TagInput from "@components/TagInput";
import WorkflowPageHeader from "@components/WorkflowPageHeader";
import { useDatasets } from "@/hooks/useDatasets";
import { usePageTitle } from "@/hooks/usePageTitle";
import type { LabelRelation } from "@/types";

import styles from "./styles.module.css";

// ================================================
// Types
// ================================================

// Client-side relation with a stable id used for React keys. The id is
// stripped before sending to the API (which expects bare LabelRelation).
type KeyedRelation = LabelRelation & { id: number };

// ================================================
// Component
// ================================================

const DatasetUpload = () => {
  usePageTitle("Upload Dataset");

  const [file, setFile] = useState<File | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [dateLabel, setDateLabel] = useState("");
  const [hasRelations, setHasRelations] = useState(false);
  const [labelRelations, setLabelRelations] = useState<KeyedRelation[]>([]);

  const relationIdRef = useRef(0);
  const nextRelationId = useCallback(() => relationIdRef.current++, []);

  const { uploadDataset } = useDatasets();
  const navigate = useNavigate();

  useEffect(() => {
    if (dateLabel && !labels.includes(dateLabel)) {
      setDateLabel("");
    }
  }, [labels, dateLabel]);

  // Drop relations whose labels no longer exist when labels change
  useEffect(() => {
    setLabelRelations((prev) => prev.filter((r) => labels.includes(r.from_label) && labels.includes(r.to_label)));
  }, [labels]);

  const addRelation = useCallback(() => {
    if (labels.length < 2) return;
    setLabelRelations((prev) => [...prev, { id: nextRelationId(), from_label: labels[0], to_label: labels[1] }]);
  }, [labels, nextRelationId]);

  const updateRelation = useCallback((id: number, field: "from_label" | "to_label", value: string) => {
    setLabelRelations((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  }, []);

  const removeRelation = useCallback((id: number) => {
    setLabelRelations((prev) => prev.filter((r) => r.id !== id));
  }, []);

  const handleFileSelect = useCallback(
    (selectedFile: File) => {
      setFile(selectedFile);
      setError(null);
      // Auto-fill dataset name from filename
      if (!datasetName) {
        const nameWithoutExt = selectedFile.name.replace(/\.[^/.]+$/, "");
        setDatasetName(nameWithoutExt);
      }
    },
    [datasetName]
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!file) {
      setError("Please select a file");
      return;
    }

    if (!datasetName.trim()) {
      setError("Please enter a dataset name");
      return;
    }

    if (labels.length === 0) {
      setError("Please enter at least one label");
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);
    setError(null);

    try {
      // Send file directly to backend with progress tracking
      await uploadDataset(
        {
          name: datasetName.trim(),
          labels: labels.join(","),
          label_relations:
            hasRelations && labelRelations.length > 0
              ? JSON.stringify(
                  // Strip the client-only id; the API expects bare LabelRelation
                  labelRelations.map(({ from_label, to_label }) => ({ from_label, to_label }))
                )
              : undefined,
          file: file,
          date_label: dateLabel || undefined,
        },
        (progress) => {
          setUploadProgress(progress);
        }
      );

      // Navigate back to datasets list
      navigate("/datasets");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload dataset");
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  };

  return (
    <Layout>
      <div className={styles.upload}>
        <WorkflowPageHeader
          title="Upload Dataset"
          backButton={{ label: "Datasets", to: "/datasets", title: "Back to datasets" }}
        />

        <div className={styles["upload__content"]}>
          <div className={styles["upload__section"]}>
            <form onSubmit={handleSubmit}>
              <div className={styles["upload__field"]}>
                <label htmlFor="datasetName" className={styles["upload__label"]}>
                  Dataset name
                </label>
                <input
                  id="datasetName"
                  type="text"
                  value={datasetName}
                  onChange={(e) => setDatasetName(e.target.value)}
                  className={styles["upload__input"]}
                  placeholder="Enter dataset name"
                  disabled={isUploading}
                />
              </div>

              <div className={styles["upload__field"]}>
                <label htmlFor="labels" className={styles["upload__label"]}>
                  Labels
                </label>
                <TagInput
                  id="labels"
                  tags={labels}
                  onChange={setLabels}
                  placeholder="e.g., diagnosis, symptom, medication"
                  disabled={isUploading}
                />
              </div>

              {/* ---- Relations checkbox ---- */}
              <label className={styles["upload__checkbox-row"]}>
                <input
                  type="checkbox"
                  checked={hasRelations}
                  onChange={(e) => {
                    setHasRelations(e.target.checked);
                    if (!e.target.checked) setLabelRelations([]);
                  }}
                  disabled={isUploading || labels.length < 2}
                />
                <span className={styles["upload__checkbox-label"]}>Some labels are related to each other</span>
              </label>

              {/* ---- Relations builder ---- */}
              {hasRelations && (
                <div className={styles["upload__relations"]}>
                  <p className={styles["upload__relations-title"]}>Label relationships</p>
                  {labelRelations.map((rel) => (
                    <div key={rel.id} className={styles["upload__relation-row"]}>
                      <select
                        className={styles["upload__relation-select"]}
                        value={rel.from_label}
                        onChange={(e) => updateRelation(rel.id, "from_label", e.target.value)}
                        disabled={isUploading}
                      >
                        {labels.map((l) => (
                          <option key={l} value={l}>
                            {l}
                          </option>
                        ))}
                      </select>
                      <span className={styles["upload__relation-op"]}>has value</span>
                      <select
                        className={styles["upload__relation-select"]}
                        value={rel.to_label}
                        onChange={(e) => updateRelation(rel.id, "to_label", e.target.value)}
                        disabled={isUploading}
                      >
                        {labels
                          .filter((l) => l !== rel.from_label)
                          .map((l) => (
                            <option key={l} value={l}>
                              {l}
                            </option>
                          ))}
                      </select>
                      <button
                        type="button"
                        className={styles["upload__relation-remove"]}
                        onClick={() => removeRelation(rel.id)}
                        disabled={isUploading}
                        title="Remove relationship"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    className={styles["upload__relation-add"]}
                    onClick={addRelation}
                    disabled={isUploading || labels.length < 2}
                  >
                    + Add relationship
                  </button>
                </div>
              )}

              <div className={styles["upload__field"]}>
                <label htmlFor="dateLabel" className={styles["upload__label"]}>
                  Date label (optional)
                </label>
                <select
                  id="dateLabel"
                  value={dateLabel}
                  onChange={(e) => setDateLabel(e.target.value)}
                  className={styles["upload__input"]}
                  disabled={isUploading || labels.length === 0}
                >
                  <option value="">-- no date label --</option>
                  {labels.map((label) => (
                    <option key={label} value={label}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>

              <div className={styles["upload__dropzone"]}>
                <p className={styles["upload__dropzone-label"]}>Upload dataset file</p>
                <FileDropzone
                  onFileSelect={handleFileSelect}
                  accept=".csv,.json"
                  maxSize={2 * 1024 * 1024 * 1024}
                  disabled={isUploading}
                />
              </div>

              {isUploading && (
                <div className={styles["upload__progress"]}>
                  <p className={styles["upload__progress-label"]}>
                    {uploadProgress >= 100 ? "Please wait while we process your dataset..." : "Uploading..."}
                  </p>
                  <ProgressBar progress={uploadProgress} />
                </div>
              )}

              {error && <div className={styles["upload__error"]}>{error}</div>}

              <div className={styles["upload__submit"]}>
                <Button
                  variant="primary"
                  type="submit"
                  label={isUploading ? (uploadProgress >= 100 ? "Processing..." : "Uploading...") : "Upload Dataset"}
                  disabled={isUploading}
                />
              </div>
            </form>
          </div>

          <aside className={styles.instructions}>
            <h2 className={styles["instructions__title"]}>Instructions</h2>
            <div className={styles["instructions__content"]}>
              <p>
                Upload your dataset file in CSV format. The file should contain the text records you want to process
                along with patient identifiers.
              </p>
              <p>
                <strong>Required columns:</strong>
                <ul>
                  <li>
                    <b>patient_id</b> - the patient identifier
                  </li>
                  <li>
                    <b>visit_date</b> - the date of the visit
                  </li>
                  <li>
                    <b>text</b> - the text of the record
                  </li>
                </ul>
              </p>
              <p>
                <strong>Optional columns:</strong>
                <ul>
                  <li>
                    <b>seq_number</b> - if a long record is split into multiple observations, this column can be used to
                    identify the sequence number of the observation
                  </li>
                </ul>
              </p>
              <p>
                <strong>Labels:</strong> Type a label and press Enter to add it. These labels represent the data
                categories in your dataset (e.g., diagnosis, symptom, event, medication). You can also paste
                comma-separated values.
              </p>
              <p>
                <strong>Date label:</strong> (optional) Pick which label corresponds to dates so extracted terms can
                inherit the right timestamp. Leave it blank to fall back to each record&rsquo;s visit_date or the upload
                time.
              </p>
              <p>
                <strong>Label relationships:</strong> (optional) Check this if some labels are semantically related. For
                each pair you define, annotators will be able to link individual annotations of those labels to each
                other using the &ldquo;Link&rdquo; button in the annotation panel.
              </p>
              <p>Maximum file size: 2GB. Supported formats: .csv, .json</p>
            </div>
          </aside>
        </div>
      </div>
    </Layout>
  );
};

export default DatasetUpload;
