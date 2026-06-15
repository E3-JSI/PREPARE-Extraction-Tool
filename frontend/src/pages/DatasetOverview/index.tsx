import { useParams, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import classNames from "classnames";
import Layout from "@/components/Layout";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useToast } from "@/hooks/useToast";
import type { DatasetOverviewOutput, Vocabulary } from "@/types";
import * as api from "@/api";
import Button from "@/components/Button";
import StatCard from "@/components/StatCard";
import WorkflowCard from "@/components/WorkflowCard";
import ProgressBar from "@/components/ProgressBar";
import ConfirmDialog from "@/components/ConfirmDialog";
import { ToastContainer } from "@/components/Toast/ToastContainer";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faObjectGroup, faMapLocationDot, faFilePen, faArrowLeft } from "@fortawesome/free-solid-svg-icons";
import { useDatasetExtractionJob } from "@/hooks/useDatasetExtractionJob";

import styles from "./styles.module.css";


// ================================================
// Helper functions
// ================================================

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function getLabelColorClass(index: number): string {
  return `labels__badge--label${(index % 9) + 1}`;
}

// ================================================
// Main Component
// ================================================

const DatasetOverview = () => {
  const { datasetId } = useParams<{ datasetId: string }>();
  const navigate = useNavigate();
  const [overview, setOverview] = useState<DatasetOverviewOutput | null>(null);
  const [vocabularies, setVocabularies] = useState<Vocabulary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isMappingAll, setIsMappingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toast = useToast();
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    variant?: "danger" | "warning" | "info";
  }>({ isOpen: false, title: "", message: "", onConfirm: () => {} });

  const parsedDatasetId = datasetId ? parseInt(datasetId, 10) : 0;

  const extraction = useDatasetExtractionJob(parsedDatasetId);

  usePageTitle(overview?.dataset.name || "Dataset Overview");

  useEffect(() => {
    const fetchOverview = async () => {
      if (!parsedDatasetId) return;

      try {
        setIsLoading(true);
        setError(null);
        const data = await api.getDatasetOverview(parsedDatasetId);
        setOverview(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load dataset overview");
      } finally {
        setIsLoading(false);
      }
    };

    fetchOverview();
  }, [parsedDatasetId]);

  // Fetch vocabularies for auto-mapping
  useEffect(() => {
    const fetchVocabularies = async () => {
      try {
        const data = await api.getVocabularies(1, 100);
        setVocabularies(data.vocabularies);
      } catch (err) {
        console.error("Failed to fetch vocabularies:", err);
      }
    };
    fetchVocabularies();
  }, []);

  const handleStartMapping = () => {
    if (!overview || vocabularies.length === 0) return;

    setConfirmDialog({
      isOpen: true,
      title: "Start Auto-Mapping",
      message: "This will auto-map all unmapped clusters using vector search across all labels. Continue?",
      variant: "warning",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          setIsMappingAll(true);
          const vocabIds = vocabularies.map((v) => v.id);
          const response = await api.autoMapAllClusters(parsedDatasetId, {
            vocabulary_ids: vocabIds,
            use_cluster_terms: true,
            search_type: "vector",
          });
          toast.success(`Auto-mapping complete! Mapped: ${response.mapped_count}, Failed: ${response.failed_count}`);
          const data = await api.getDatasetOverview(parsedDatasetId);
          setOverview(data);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to start mapping");
        } finally {
          setIsMappingAll(false);
        }
      },
    });
  };

  const handleExtractAll = () => {
    if (!overview || extraction.isRunning) return;

    setConfirmDialog({
      isOpen: true,
      title: "Extract All Terms",
      message: `This will extract terms from all ${overview.stats.total_records} record${overview.stats.total_records !== 1 ? "s" : ""} in the dataset. This may take several minutes. Continue?`,
      variant: "warning",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          await extraction.startExtraction(overview.dataset.labels);
          toast.success("Terms extracted successfully for all records");
          const data = await api.getDatasetOverview(parsedDatasetId);
          setOverview(data);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to extract terms");
        }
      },
    });
  };

  const handleCancelExtraction = async () => {
    try {
      await extraction.cancelExtraction();
      toast.warning("Extraction was cancelled");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel extraction");
    }
  };

  const handleAutoClustering = () => {
    if (!overview || overview.dataset.labels.length === 0) return;

    const labels = overview.dataset.labels;

    setConfirmDialog({
      isOpen: true,
      title: "Auto-Cluster Terms",
      message: `This will automatically cluster all extracted terms across all ${labels.length} label${labels.length !== 1 ? "s" : ""}. Continue?`,
      variant: "warning",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          await Promise.all(labels.map((label) => api.rebuildClusters(parsedDatasetId, label)));
          toast.success("Auto-clustering completed successfully");
          const data = await api.getDatasetOverview(parsedDatasetId);
          setOverview(data);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to auto-cluster");
        }
      },
    });
  };

  if (!parsedDatasetId) {
    return (
      <Layout>
        <div className={styles.page}>
          <div className={styles["page--error"]}>Invalid dataset ID</div>
        </div>
      </Layout>
    );
  }

  if (isLoading) {
    return (
      <Layout>
        <div className={styles.page}>
          <div className={styles["page--loading"]}>Loading dataset overview...</div>
        </div>
      </Layout>
    );
  }

  if (error || !overview) {
    return (
      <Layout>
        <div className={styles.page}>
          <div className={styles["page--error"]}>{error || "Failed to load dataset"}</div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className={styles.page}>
        {/* Header Section */}
        <div className={styles.header}>
          <div className={styles["header__title-section"]}>
            <Button variant="outline" size="icon" onClick={() => navigate("/datasets")} aria-label="Back to Datasets">
              <FontAwesomeIcon icon={faArrowLeft} />
            </Button>
            <div>
              <h1 className={styles.header__title}>{overview.dataset.name}</h1>
              <p className={styles.header__subtitle}>Dataset Overview and Statistics</p>
            </div>
          </div>
        </div>

        {/* Labels Section */}
        {overview.dataset.labels.length > 0 && (
          <div className={styles.labels}>
            <span className={styles.labels__title}>Labels:</span>
            <div className={styles.labels__list}>
              {overview.dataset.labels.map((label, idx) => (
                <span key={idx} className={classNames(styles["labels__badge"], styles[getLabelColorClass(idx)])}>
                  {label}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Metadata Section */}
        <div className={styles.metadata}>
          <div className={styles.metadata__item}>
            <span className={styles.metadata__label}>Uploaded:</span>
            <span className={styles.metadata__value}>{formatDate(overview.dataset.uploaded)}</span>
          </div>
        </div>

        {/* Statistics Cards */}
        <div className={styles.statsGrid}>
          <StatCard label="Total Records" value={overview.stats.total_records} />
          <StatCard label="Records Processed" value={overview.stats.processed_count} color="green" />
          <StatCard label="Total Terms" value={overview.stats.extracted_terms_count} color="blue" />
          <StatCard label="Pending Review" value={overview.stats.pending_review_count} color="orange" />
        </div>

        {/* Workflow Section */}
        <div className={styles.workflow}>
          <h2 className={styles.workflow__title}>Workflow Steps</h2>

          {extraction.isRunning && (
            <div className={styles["extraction-banner"]}>
              <span className={styles["extraction-banner__label"]}>
                Extraction in progress
                {extraction.progress && extraction.progress.total > 0
                  ? `: ${extraction.progress.completed} / ${extraction.progress.total} records`
                  : "…"}
              </span>
              <div className={styles["extraction-banner__bar"]}>
                <ProgressBar
                  progress={
                    extraction.progress && extraction.progress.total > 0
                      ? (extraction.progress.completed / extraction.progress.total) * 100
                      : 0
                  }
                  showPercentage
                />
              </div>
              <Button
                variant="outline"
                size="small"
                onClick={handleCancelExtraction}
                disabled={extraction.isCancelling}
              >
                {extraction.isCancelling ? "Cancelling…" : "Cancel"}
              </Button>
            </div>
          )}

          <div className={styles.workflow__grid}>
            {/* Term Extraction Card */}
            <WorkflowCard
              title="Term Extraction"
              description="Extract medical entities from clinical text"
              icon={faFilePen}
              stats={[
                { label: "Total Records", value: overview.stats.total_records },
                { label: "Terms Extracted", value: overview.stats.extracted_terms_count },
              ]}
              progress={
                extraction.isRunning && extraction.progress && extraction.progress.total > 0
                  ? { current: extraction.progress.completed, total: extraction.progress.total }
                  : {
                      current: overview.stats.total_records - overview.stats.pending_review_count,
                      total: overview.stats.total_records,
                    }
              }
              actions={[
                {
                  label: "View Records",
                  onClick: () => navigate(`/datasets/${datasetId}/records`),
                  variant: "primary",
                },
                {
                  label: extraction.isRunning ? "Extract All (running…)" : "Extract All",
                  onClick: handleExtractAll,
                  variant: "secondary",
                  disabled: extraction.isRunning,
                },
              ]}
            />

            {/* Term Clustering Card */}
            <WorkflowCard
              title="Term Clustering"
              description="Group similar terms for standardization"
              icon={faObjectGroup}
              stats={[
                { label: "Clusters Created", value: overview.clustering_stats.total_clusters },
                { label: "Clustered Terms", value: overview.clustering_stats.clustered_terms },
                { label: "Unclustered Terms", value: overview.clustering_stats.unclustered_terms },
              ]}
              actions={[
                {
                  label: "View Clusters",
                  onClick: () => navigate(`/datasets/${datasetId}/clusters`),
                  variant: "primary",
                },
                {
                  label: "Auto-Cluster",
                  onClick: handleAutoClustering,
                  variant: "secondary",
                },
              ]}
            />

            {/* Concept Mapping Card */}
            <WorkflowCard
              title="Concept Mapping"
              description="Map clusters to standard vocabulary concepts"
              icon={faMapLocationDot}
              stats={[
                { label: "Total Clusters", value: overview.mapping_stats.total_clusters },
                { label: "Mapped Clusters", value: overview.mapping_stats.mapped_clusters },
                { label: "Unmapped Clusters", value: overview.mapping_stats.unmapped_clusters },
              ]}
              progress={{
                current: overview.mapping_stats.mapped_clusters,
                total: overview.mapping_stats.total_clusters,
              }}
              actions={[
                {
                  label: "View Mappings",
                  onClick: () => navigate(`/datasets/${datasetId}/mapping`),
                  variant: "primary",
                },
                {
                  label: isMappingAll ? "Mapping..." : "Start Mapping",
                  onClick: handleStartMapping,
                  variant: "secondary",
                  disabled: isMappingAll,
                },
              ]}
            />
          </div>
        </div>

        <ToastContainer toasts={toast.toasts} onDismiss={toast.dismissToast} />

        <ConfirmDialog
          isOpen={confirmDialog.isOpen}
          title={confirmDialog.title}
          message={confirmDialog.message}
          variant={confirmDialog.variant}
          onConfirm={confirmDialog.onConfirm}
          onCancel={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
        />
      </div>
    </Layout>
  );
};

export default DatasetOverview;
