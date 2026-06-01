import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "@components/Layout";
import FileDropzone from "@components/FileDropzone";
import Button from "@components/Button";
import ProgressBar from "@/components/ProgressBar/index";
import TagInput from "@components/TagInput";
import { useDatasets } from "@/hooks/useDatasets";
import { usePageTitle } from "@/hooks/usePageTitle";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faArrowLeft } from "@fortawesome/free-solid-svg-icons";

import styles from "./styles.module.css";

// Note: File parsing is handled by the backend

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

  const { uploadDataset } = useDatasets();
  const navigate = useNavigate();

  useEffect(() => {
    if (dateLabel && !labels.includes(dateLabel)) {
      setDateLabel("");
    }
  }, [labels, dateLabel]);

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
          file: file,
          date_label: dateLabel || undefined,
        },
        (progress) => {
          console.log("Upload progress:", progress.toFixed(2) + "%");
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

  const sidebar = (
    <div className={styles["upload__sidebar"]}>
      <Button variant="outline" onClick={() => navigate("/datasets")} title="Back to datasets">
        <FontAwesomeIcon icon={faArrowLeft} /> Datasets
      </Button>
    </div>
  );

  return (
    <Layout sidebar={sidebar}>
      <div className={styles.upload}>
        <h1 className={styles["upload__title"]}>Upload Dataset</h1>

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
              <p>Maximum file size: 2GB. Supported formats: .csv, .json</p>
            </div>
          </aside>
        </div>
      </div>
    </Layout>
  );
};

export default DatasetUpload;
