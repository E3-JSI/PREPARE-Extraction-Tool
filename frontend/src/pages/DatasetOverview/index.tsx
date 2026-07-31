import { useParams, useNavigate } from "react-router-dom";
import { useCallback, useEffect, useRef, useState } from "react";
import classNames from "classnames";
import Layout from "@/components/Layout";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useToast } from "@/hooks/useToast";
import type { DatasetOverviewOutput, Vocabulary } from "@/types";
import * as api from "@/api";
import Button from "@/components/Button";
import StatCard from "@/components/StatCard";
import WorkflowCard from "@/components/WorkflowCard";
import WorkflowPageHeader from "@/components/WorkflowPageHeader";
import ProgressBar from "@/components/ProgressBar";
import ConfirmDialog from "@/components/ConfirmDialog";
import { ToastContainer } from "@/components/Toast/ToastContainer";
import { faObjectGroup, faMapLocationDot, faFilePen } from "@fortawesome/free-solid-svg-icons";
import { useDatasetExtractionJob } from "@/hooks/useDatasetExtractionJob";
import { useAutoMapJob, type AutoMapJobProgress } from "@/hooks/useAutoMapJob";
import { useClusterAllJob } from "@/hooks/useClusterAllJob";
import { formatClusterAllSummary } from "@/utils/clusterSummary";

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

  // Tracks whether the component is still mounted so async callbacks can avoid
  // setState-after-unmount when refetching the overview after an action.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const extraction = useDatasetExtractionJob(parsedDatasetId);
  const clusterAll = useClusterAllJob(parsedDatasetId);

  // Auto-map-all completion (explicit run or resumed job) toasts the counts and
  // refreshes the overview stats.
  const handleAutoMapComplete = useCallback(
    async (p: AutoMapJobProgress) => {
      if (p.status === "cancelled") {
        toast.warning(`Auto-mapping cancelled. Mapped: ${p.mapped_count}, Failed: ${p.failed_count}`);
      } else {
        toast.success(`Auto-mapping complete! Mapped: ${p.mapped_count}, Failed: ${p.failed_count}`);
      }
      try {
        const data = await api.getDatasetOverview(parsedDatasetId);
        if (mountedRef.current) setOverview(data);
      } catch {
        // Non-critical: the toast already reported the result.
      }
    },
    [toast, parsedDatasetId]
  );

  const autoMap = useAutoMapJob(parsedDatasetId, handleAutoMapComplete);

  usePageTitle(overview?.dataset.name || "Dataset Overview");

  useEffect(() => {
    let ignore = false;

    const fetchOverview = async () => {
      if (!parsedDatasetId) return;

      try {
        setIsLoading(true);
        setError(null);
        const data = await api.getDatasetOverview(parsedDatasetId);
        if (ignore) return;
        setOverview(data);
      } catch (err) {
        if (ignore) return;
        setError(err instanceof Error ? err.message : "Failed to load dataset overview");
      } finally {
        if (!ignore) setIsLoading(false);
      }
    };

    fetchOverview();

    return () => {
      ignore = true;
    };
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
          await autoMap.startAutoMap({
            vocabulary_ids: vocabularies.map((v) => v.id),
            use_cluster_terms: true,
            search_type: "vector",
          });
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to start mapping");
        }
      },
    });
  };

  const handleCancelMapping = async () => {
    try {
      await autoMap.cancelAutoMap();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel auto-mapping");
    }
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
          if (mountedRef.current) setOverview(data);
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
    if (!overview || overview.dataset.labels.length === 0 || clusterAll.isRunning) return;

    const labels = overview.dataset.labels;

    setConfirmDialog({
      isOpen: true,
      title: "Auto-Cluster Terms",
      message: `This will automatically cluster all extracted terms across all ${labels.length} label${labels.length !== 1 ? "s" : ""}. Labels with reviewed clusters are skipped. Continue?`,
      variant: "warning",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          const result = await clusterAll.startClusterAll();
          if (result) {
            toast.success(formatClusterAllSummary(result.clustered_labels, result.skipped_labels));
          }
          const data = await api.getDatasetOverview(parsedDatasetId);
          if (mountedRef.current) setOverview(data);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to auto-cluster");
        }
      },
    });
  };

  const handleCancelClusterAll = async () => {
    try {
      await clusterAll.cancelClusterAll();
      toast.warning("Clustering was cancelled");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel clustering");
    }
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
        <WorkflowPageHeader
          title={overview.dataset.name}
          subtitle="Dataset Overview and Statistics"
          backButton={{ label: "Back to Datasets", to: "/datasets", title: "Back to Datasets" }}
        />

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

          {autoMap.isRunning && (
            <div className={styles["extraction-banner"]}>
              <span className={styles["extraction-banner__label"]}>
                Auto-mapping in progress
                {autoMap.progress && autoMap.progress.total > 0
                  ? `: ${autoMap.progress.completed} / ${autoMap.progress.total} clusters`
                  : "…"}
              </span>
              <div className={styles["extraction-banner__bar"]}>
                <ProgressBar
                  progress={
                    autoMap.progress && autoMap.progress.total > 0
                      ? (autoMap.progress.completed / autoMap.progress.total) * 100
                      : 0
                  }
                  showPercentage
                />
              </div>
              <Button variant="outline" size="small" onClick={handleCancelMapping} disabled={autoMap.isCancelling}>
                {autoMap.isCancelling ? "Cancelling…" : "Cancel"}
              </Button>
            </div>
          )}

          {clusterAll.isRunning && (
            <div className={styles["extraction-banner"]}>
              <span className={styles["extraction-banner__label"]}>
                Clustering in progress
                {clusterAll.progress && clusterAll.progress.total > 0
                  ? `: ${clusterAll.progress.completed} / ${clusterAll.progress.total} labels`
                  : "…"}
              </span>
              <div className={styles["extraction-banner__bar"]}>
                <ProgressBar
                  progress={
                    clusterAll.progress && clusterAll.progress.total > 0
                      ? (clusterAll.progress.completed / clusterAll.progress.total) * 100
                      : 0
                  }
                  showPercentage
                />
              </div>
              <Button
                variant="outline"
                size="small"
                onClick={handleCancelClusterAll}
                disabled={clusterAll.isCancelling}
              >
                {clusterAll.isCancelling ? "Cancelling…" : "Cancel"}
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
              progress={
                clusterAll.isRunning && clusterAll.progress && clusterAll.progress.total > 0
                  ? { current: clusterAll.progress.completed, total: clusterAll.progress.total }
                  : undefined
              }
              actions={[
                {
                  label: "View Clusters",
                  onClick: () => navigate(`/datasets/${datasetId}/clusters`),
                  variant: "primary",
                },
                {
                  label: clusterAll.isRunning ? "Auto-Cluster (running…)" : "Auto-Cluster",
                  onClick: handleAutoClustering,
                  variant: "secondary",
                  disabled: clusterAll.isRunning,
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
                  label: autoMap.isRunning ? "Mapping..." : "Start Mapping",
                  onClick: handleStartMapping,
                  variant: "secondary",
                  disabled: autoMap.isRunning,
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
