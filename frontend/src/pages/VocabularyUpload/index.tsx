import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "@components/Layout";
import FileDropzone from "@components/FileDropzone";
import Button from "@components/Button";
import ProgressBar from "@/components/ProgressBar/index";
import { useVocabularies } from "@/hooks/useVocabularies";
import { usePageTitle } from "@/hooks/usePageTitle";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faArrowLeft } from "@fortawesome/free-solid-svg-icons";
import styles from "./styles.module.css";

// Note: File parsing is handled by the backend

// ================================================
// Component
// ================================================

const VocabularyUpload = () => {
  usePageTitle("Upload Vocabulary");

  const [file, setFile] = useState<File | null>(null);
  const [vocabularyName, setVocabularyName] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const { addVocabulary } = useVocabularies();
  const navigate = useNavigate();

  const handleFileSelect = useCallback(
    (selectedFile: File) => {
      setFile(selectedFile);
      setError(null);
      // Auto-fill vocabulary name from filename
      if (!vocabularyName) {
        const nameWithoutExt = selectedFile.name.replace(/\.[^/.]+$/, "");
        setVocabularyName(nameWithoutExt);
      }
    },
    [vocabularyName]
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!file) {
      setError("Please select a file");
      return;
    }

    if (!vocabularyName.trim()) {
      setError("Please enter a vocabulary name");
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);
    setError(null);

    try {
      // Send file directly to backend with progress tracking
      await addVocabulary(
        {
          name: vocabularyName.trim(),
          file: file,
        },
        (progress) => {
          console.log("Upload progress:", progress.toFixed(2) + "%");
          setUploadProgress(progress);
        }
      );

      // Navigate back to vocabularies list
      navigate("/vocabularies");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload vocabulary");
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  };

  const sidebar = (
    <div className={styles["upload__sidebar"]}>
      <Button variant="outline" onClick={() => navigate("/vocabularies")} title="Back to vocabularies">
        <FontAwesomeIcon icon={faArrowLeft} /> Vocabularies
      </Button>
    </div>
  );

  return (
    <Layout sidebar={sidebar}>
      <div className={styles.upload}>
        <h1 className={styles["upload__title"]}>Upload Vocabulary</h1>

        <div className={styles["upload__content"]}>
          <div className={styles["upload__section"]}>
            <form onSubmit={handleSubmit}>
              <div className={styles["upload__dropzone"]}>
                <p className={styles["upload__dropzone-label"]}>Upload vocabulary file</p>
                <FileDropzone
                  onFileSelect={handleFileSelect}
                  accept=".csv"
                  maxSize={2 * 1024 * 1024 * 1024}
                  disabled={isUploading}
                />
              </div>

              {isUploading && (
                <div className={styles["upload__progress"]}>
                  <p className={styles["upload__progress-label"]}>
                    {uploadProgress >= 100 ? "Please wait while we process your vocabulary..." : "Uploading..."}
                  </p>
                  <ProgressBar progress={uploadProgress} />
                </div>
              )}

              {error && <div className={styles["upload__error"]}>{error}</div>}

              <div className={styles["upload__submit"]}>
                <Button
                  variant="primary"
                  type="submit"
                  label={isUploading ? (uploadProgress >= 100 ? "Processing..." : "Uploading...") : "Upload Vocabulary"}
                  disabled={isUploading}
                />
              </div>
            </form>
          </div>

          <aside className={styles.instructions}>
            <h2 className={styles["instructions__title"]}>Instructions</h2>
            <div className={styles["instructions__content"]}>
              <p>
                Upload your vocabulary file as a tab-delimited CSV file. The file should contain the concepts with all
                required OMOP CDM vocabulary fields.
              </p>
              <p>
                <strong>Required columns:</strong> concept_id, concept_name, domain_id, concept_class_id,
                standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason
              </p>
              <p>
                <strong>Date format:</strong> Dates must be in YYYYMMDD format (e.g., 20240101 for January 1, 2024).
              </p>
              <p>
                The vocabulary will be indexed for semantic search after upload. Maximum file size: 2GB. Supported
                format: .csv (tab-delimited)
              </p>
            </div>
          </aside>
        </div>
      </div>
    </Layout>
  );
};

export default VocabularyUpload;
