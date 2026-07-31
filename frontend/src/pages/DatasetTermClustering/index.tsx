import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useParams } from "react-router-dom";
import { DndContext, DragOverlay } from "@dnd-kit/core";
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import classNames from "classnames";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faArrowUp, faCheck, faPlus } from "@fortawesome/free-solid-svg-icons";

import Layout from "@components/Layout";
import Button from "@components/Button";
import { Select } from "@components/Select";
import StatCard from "@components/StatCard";
import ConfirmDialog from "@components/ConfirmDialog";
import { ToastContainer } from "@components/Toast/ToastContainer";
import WorkflowPageHeader from "@components/WorkflowPageHeader";
import ClusterCard from "@components/ClusterCard";
import ClusterOverlay from "@components/ClusterOverlay";
import DroppableUnclusteredArea from "@components/DroppableUnclusteredArea";
import TermOverlay from "@components/TermOverlay";
import ProgressBar from "@components/ProgressBar";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useToast } from "@/hooks/useToast";
import { useClusterAllJob } from "@/hooks/useClusterAllJob";
import { formatClusterAllSummary } from "@/utils/clusterSummary";
import * as api from "@/api";

import type { ClusterData, ClusteredTerm } from "@/types";

import styles from "./styles.module.css";

export default function DatasetTermClustering() {
  const { datasetId } = useParams<{ datasetId: string }>();
  const [clusters, setClusters] = useState<ClusterData[]>([]);
  const [unclusteredTerms, setUnclusteredTerms] = useState<ClusteredTerm[]>([]);
  const [labels, setLabels] = useState<string[]>([]);
  const [selectedLabel, setSelectedLabel] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isAutoClustering, setIsAutoClustering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [datasetName, setDatasetName] = useState<string>("");
  const [activeDragTerm, setActiveDragTerm] = useState<ClusteredTerm | null>(null);
  const [activeDragCluster, setActiveDragCluster] = useState<ClusterData | null>(null);
  const [showBackToTop, setShowBackToTop] = useState(false);
  const [isDownloadingClusters, setIsDownloadingClusters] = useState(false);
  const [activeLetter, setActiveLetter] = useState("");
  const [labelReviewed, setLabelReviewed] = useState(false);
  const [isTogglingReview, setIsTogglingReview] = useState(false);

  const toast = useToast();
  const parsedDatasetId = datasetId ? parseInt(datasetId, 10) : 0;
  const clusterAll = useClusterAllJob(parsedDatasetId);
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: (inputValue?: string) => void;
    variant?: "danger" | "warning" | "info";
    showInput?: boolean;
    inputPlaceholder?: string;
  }>({ isOpen: false, title: "", message: "", onConfirm: () => {} });

  usePageTitle(datasetName ? `Term Clustering - ${datasetName}` : "Term Clustering");

  // Back-to-top scroll listener
  useEffect(() => {
    const handleScroll = () => {
      setShowBackToTop(window.scrollY > 300);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Fetch dataset info
  useEffect(() => {
    const fetchDataset = async () => {
      if (!datasetId) return;
      try {
        const data = await api.getDataset(parseInt(datasetId));
        setDatasetName(data.dataset.name);
      } catch (err) {
        console.error("Failed to fetch dataset:", err);
      }
    };
    fetchDataset();
  }, [datasetId]);

  // Fetch labels first to initialize the filter
  useEffect(() => {
    const fetchLabels = async () => {
      if (!datasetId) return;
      try {
        // Fetch once to get labels, passing undefined gets all data including labels
        const data = await api.getClusters(parseInt(datasetId), undefined);
        setLabels(data.labels);
        // Set default label to first label
        if (data.labels.length > 0) {
          setSelectedLabel(data.labels[0]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load labels");
      }
    };
    fetchLabels();
  }, [datasetId]);

  // Fetch clusters when label is selected
  const fetchClusters = useCallback(
    async (silent = false) => {
      if (!datasetId || !selectedLabel) return;

      try {
        if (!silent) setIsLoading(true);
        setError(null);
        const data = await api.getClusters(parseInt(datasetId), selectedLabel);
        setClusters(data.clusters);
        setUnclusteredTerms(data.unclustered_terms);
        setLabelReviewed(data.label_reviewed);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load clusters");
      } finally {
        if (!silent) setIsLoading(false);
      }
    },
    [datasetId, selectedLabel]
  );

  useEffect(() => {
    fetchClusters();
  }, [fetchClusters]);

  // Handle auto-clustering
  const handleAutoClustering = async () => {
    if (!datasetId || !selectedLabel) return;

    try {
      setIsAutoClustering(true);
      await api.rebuildClusters(parseInt(datasetId), selectedLabel);
      await fetchClusters();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Auto-clustering failed");
    } finally {
      setIsAutoClustering(false);
    }
  };

  // Cluster every label in the dataset via the shared background job. Labels with
  // a reviewed cluster are skipped server-side (re-clustering is destructive).
  const handleClusterAll = async () => {
    if (!parsedDatasetId || clusterAll.isRunning) return;

    try {
      const result = await clusterAll.startClusterAll();
      if (result) {
        toast.success(formatClusterAllSummary(result.clustered_labels, result.skipped_labels));
      }
      await fetchClusters();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Cluster All Labels failed");
    }
  };

  const handleCancelClusterAll = async () => {
    try {
      await clusterAll.cancelClusterAll();
      toast.warning("Clustering was cancelled");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel clustering");
    }
  };

  const handleDownloadClusters = useCallback(async () => {
    if (!datasetId) return;
    try {
      setIsDownloadingClusters(true);
      await api.downloadClusters(parseInt(datasetId, 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download clusters");
    } finally {
      setIsDownloadingClusters(false);
    }
  }, [datasetId]);

  const handleToggleReview = useCallback(async () => {
    if (!datasetId || !selectedLabel) return;
    try {
      setIsTogglingReview(true);
      if (labelReviewed) {
        await api.unreviewLabel(parseInt(datasetId), selectedLabel);
        setLabelReviewed(false);
      } else {
        await api.reviewLabel(parseInt(datasetId), selectedLabel);
        setLabelReviewed(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update review status");
    } finally {
      setIsTogglingReview(false);
    }
  }, [datasetId, selectedLabel, labelReviewed]);

  // Helper function to recalculate cluster stats
  const recalculateClusterStats = (cluster: ClusterData): ClusterData => {
    const totalTerms = cluster.terms.length;
    const totalOccurrences = cluster.terms.reduce((sum, t) => sum + t.frequency, 0);
    const uniqueRecordIds = new Set(cluster.terms.flatMap((t) => t.record_ids));
    const uniqueRecords = uniqueRecordIds.size;

    return {
      ...cluster,
      total_terms: totalTerms,
      total_occurrences: totalOccurrences,
      unique_records: uniqueRecords,
    };
  };

  // Handle drag start (dnd-kit)
  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event;
    const dragType = active.data.current?.type;

    if (dragType === "cluster") {
      const cluster = active.data.current?.cluster as ClusterData | undefined;
      if (cluster) {
        setActiveDragCluster(cluster);
        setActiveDragTerm(null);
      }
    } else {
      const term = active.data.current?.term as ClusteredTerm | undefined;
      if (term) {
        setActiveDragTerm(term);
        setActiveDragCluster(null);
      }
    }
  };

  // Handle cluster merge
  const handleClusterMerge = (sourceClusterId: number, targetClusterId: number) => {
    const sourceCluster = clusters.find((c) => c.id === sourceClusterId);
    const targetCluster = clusters.find((c) => c.id === targetClusterId);

    if (!sourceCluster || !targetCluster) return;

    // Store original state for rollback
    const originalClusters = clusters;

    // Optimistic update: merge source terms into target, remove source cluster
    // Use a Map to merge terms by text (case-insensitive)
    const termMap = new Map<string, ClusteredTerm>();

    // Add target terms first
    for (const term of targetCluster.terms) {
      termMap.set(term.text.toLowerCase(), { ...term });
    }

    // Merge source terms
    for (const sourceTerm of sourceCluster.terms) {
      const key = sourceTerm.text.toLowerCase();
      const existing = termMap.get(key);
      if (existing) {
        // Merge: combine frequencies and record_ids
        const mergedRecordIds = [...new Set([...existing.record_ids, ...sourceTerm.record_ids])];
        termMap.set(key, {
          ...existing,
          frequency: existing.frequency + sourceTerm.frequency,
          record_ids: mergedRecordIds,
          n_records: mergedRecordIds.length,
        });
      } else {
        termMap.set(key, { ...sourceTerm });
      }
    }

    const mergedTerms = Array.from(termMap.values());

    const mergedCluster = recalculateClusterStats({
      ...targetCluster,
      terms: mergedTerms,
    });

    // Update state: replace target with merged, remove source
    setClusters((prev) =>
      prev.map((c) => (c.id === targetClusterId ? mergedCluster : c)).filter((c) => c.id !== sourceClusterId)
    );

    // API call in background
    api
      .mergeClusters(parseInt(datasetId!), {
        cluster_ids: [targetClusterId, sourceClusterId],
        new_title: targetCluster.title,
      })
      .then(() => {
        // Silently refresh to sync with backend (gets the new cluster ID)
        fetchClusters(true);
      })
      .catch((err) => {
        // Rollback on error
        setClusters(originalClusters);
        setError(err instanceof Error ? err.message : "Failed to merge clusters");
      });
  };

  // Handle drag end (dnd-kit)
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    const dragType = active.data.current?.type;

    // Reset drag states
    setActiveDragTerm(null);
    setActiveDragCluster(null);

    if (!over) return;

    // Handle cluster drag (merging)
    if (dragType === "cluster") {
      const sourceClusterId = active.data.current?.clusterId as number;
      const targetClusterId = over.data.current?.clusterId as number | undefined;

      // Only merge if dropping on a different cluster
      if (targetClusterId && targetClusterId !== sourceClusterId) {
        handleClusterMerge(sourceClusterId, targetClusterId);
      }
      return;
    }

    // Handle term drag (existing logic)
    const termId = active.data.current?.termId as number;
    const sourceClusterId = active.data.current?.sourceClusterId as number | null;
    const targetClusterId = over.data.current?.clusterId as number | null;

    // Don't do anything if dropping in same cluster
    if (sourceClusterId === targetClusterId) return;

    // Optimistic update
    const term = findTermById(termId);
    if (!term) return;

    // Store original state for rollback
    const originalClusters = clusters;
    const originalUnclustered = unclusteredTerms;

    // Check if source cluster will be empty after removing the term
    let sourceClusterWillBeEmpty = false;
    if (sourceClusterId !== null) {
      const sourceCluster = clusters.find((c) => c.id === sourceClusterId);
      sourceClusterWillBeEmpty = sourceCluster?.terms.length === 1;
    }

    // Remove from source (or delete source cluster if it becomes empty)
    if (sourceClusterId === null) {
      setUnclusteredTerms((prev) => prev.filter((t) => t.term_id !== termId));
    } else if (sourceClusterWillBeEmpty) {
      // Remove the entire cluster if it becomes empty
      setClusters((prev) => prev.filter((c) => c.id !== sourceClusterId));
    } else {
      setClusters((prev) =>
        prev.map((c) => {
          if (c.id === sourceClusterId) {
            const updated = {
              ...c,
              terms: c.terms.filter((t) => t.term_id !== termId),
            };
            return recalculateClusterStats(updated);
          }
          return c;
        })
      );
    }

    // Add to target (merge if same text exists in target cluster)
    if (targetClusterId === null) {
      // Check for duplicate in unclustered
      const existingUnclustered = unclusteredTerms.find(
        (t) => t.text.toLowerCase() === term.text.toLowerCase() && t.term_id !== termId
      );
      if (existingUnclustered) {
        // Merge: update existing term's stats
        setUnclusteredTerms((prev) =>
          prev.map((t) => {
            if (t.term_id === existingUnclustered.term_id) {
              return {
                ...t,
                frequency: t.frequency + term.frequency,
                n_records: new Set([...t.record_ids, ...term.record_ids]).size,
                record_ids: [...new Set([...t.record_ids, ...term.record_ids])],
              };
            }
            return t;
          })
        );
      } else {
        setUnclusteredTerms((prev) => [...prev, term]);
      }
    } else {
      setClusters((prev) =>
        prev.map((c) => {
          if (c.id === targetClusterId) {
            // Check if a term with the same text already exists in this cluster
            const existingTerm = c.terms.find(
              (t) => t.text.toLowerCase() === term.text.toLowerCase() && t.term_id !== termId
            );
            let updated: ClusterData;
            if (existingTerm) {
              // Merge: update existing term's frequency and record_ids
              updated = {
                ...c,
                terms: c.terms.map((t) => {
                  if (t.term_id === existingTerm.term_id) {
                    return {
                      ...t,
                      frequency: t.frequency + term.frequency,
                      n_records: new Set([...t.record_ids, ...term.record_ids]).size,
                      record_ids: [...new Set([...t.record_ids, ...term.record_ids])],
                    };
                  }
                  return t;
                }),
              };
            } else {
              // No duplicate, just add the term
              updated = {
                ...c,
                terms: [...c.terms, term],
              };
            }
            return recalculateClusterStats(updated);
          }
          return c;
        })
      );
    }

    // API calls in background
    const apiCalls: Promise<unknown>[] = [];

    if (targetClusterId === null) {
      apiCalls.push(api.unassignTermFromCluster(termId));
    } else {
      apiCalls.push(api.assignTermToCluster(termId, targetClusterId));
    }

    // Delete source cluster if it became empty
    // if (sourceClusterWillBeEmpty && sourceClusterId !== null) {
    //   apiCalls.push(api.deleteCluster(sourceClusterId));
    // }

    Promise.all(apiCalls).catch((err) => {
      // Rollback on error
      setClusters(originalClusters);
      setUnclusteredTerms(originalUnclustered);
      setError(err instanceof Error ? err.message : "Failed to move term");
    });
  };

  const findTermById = (termId: number): ClusteredTerm | undefined => {
    for (const cluster of clusters) {
      const term = cluster.terms.find((t) => t.term_id === termId);
      if (term) return term;
    }
    return unclusteredTerms.find((t) => t.term_id === termId);
  };

  // Handle cluster rename
  const handleRename = async (clusterId: number, newTitle: string) => {
    // Optimistic update
    const originalClusters = clusters;
    setClusters((prev) => prev.map((c) => (c.id === clusterId ? { ...c, title: newTitle } : c)));

    // Scroll to the renamed cluster after React re-renders with the new sort order
    setTimeout(() => {
      const element = document.querySelector(`[data-cluster-id="${CSS.escape(String(clusterId))}"]`);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 0);

    try {
      await api.renameCluster(clusterId, newTitle);
    } catch (err) {
      // Rollback on error
      setClusters(originalClusters);
      setError(err instanceof Error ? err.message : "Failed to rename cluster");
    }
  };

  // Handle cluster delete
  const handleDelete = (clusterId: number) => {
    setConfirmDialog({
      isOpen: true,
      title: "Delete Cluster",
      message: "Are you sure you want to delete this cluster? Terms will become unclustered.",
      variant: "danger",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));

        const originalClusters = clusters;
        const originalUnclustered = unclusteredTerms;

        const clusterToDelete = clusters.find((c) => c.id === clusterId);
        if (!clusterToDelete) return;

        // Optimistic update
        setClusters((prev) => prev.filter((c) => c.id !== clusterId));
        setUnclusteredTerms((prev) => [...prev, ...clusterToDelete.terms]);

        try {
          await api.deleteCluster(clusterId);
        } catch (err) {
          setClusters(originalClusters);
          setUnclusteredTerms(originalUnclustered);
          setError(err instanceof Error ? err.message : "Failed to delete cluster");
        }
      },
    });
  };

  // Handle term removal from cluster
  const handleRemoveTerm = async (termId: number) => {
    const term = findTermById(termId);
    if (!term) return;

    // Find which cluster contains this term
    const sourceCluster = clusters.find((c) => c.terms.some((t) => t.term_id === termId));
    if (!sourceCluster) return;

    const originalClusters = clusters;
    const originalUnclustered = unclusteredTerms;

    // Check if cluster will be empty after removal
    const clusterWillBeEmpty = sourceCluster.terms.length === 1;

    // Optimistic update: remove term from cluster
    if (clusterWillBeEmpty) {
      setClusters((prev) => prev.filter((c) => c.id !== sourceCluster.id));
    } else {
      setClusters((prev) =>
        prev.map((c) => {
          if (c.id === sourceCluster.id) {
            const updated = {
              ...c,
              terms: c.terms.filter((t) => t.term_id !== termId),
            };
            return recalculateClusterStats(updated);
          }
          return c;
        })
      );
    }

    // Add term to unclustered
    setUnclusteredTerms((prev) => [...prev, term]);

    // API calls
    const apiCalls: Promise<unknown>[] = [api.unassignTermFromCluster(termId)];

    if (clusterWillBeEmpty) {
      apiCalls.push(api.deleteCluster(sourceCluster.id));
    }

    try {
      await Promise.all(apiCalls);
    } catch (err) {
      // Rollback on error
      setClusters(originalClusters);
      setUnclusteredTerms(originalUnclustered);
      setError(err instanceof Error ? err.message : "Failed to remove term");
    }
  };

  // Create new cluster
  const handleCreateCluster = () => {
    if (!datasetId || !selectedLabel) return;

    setConfirmDialog({
      isOpen: true,
      title: "Create New Cluster",
      message: "Enter a name for the new cluster:",
      variant: "info",
      showInput: true,
      inputPlaceholder: "Cluster name",
      onConfirm: async (inputValue?: string) => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        if (!inputValue) return;

        try {
          const newCluster = await api.createCluster(parseInt(datasetId), {
            label: selectedLabel,
            title: inputValue,
          });
          setClusters((prev) => [...prev, newCluster]);
          setTimeout(() => {
            const element = document.querySelector(`[data-cluster-id="${CSS.escape(String(newCluster.id))}"]`);
            if (element) {
              element.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          }, 100);
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to create cluster");
        }
      },
    });
  };

  // Filter and sort clusters by search
  const filteredClusters = useMemo(() => {
    let result = clusters;
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = clusters.filter(
        (c) => c.title.toLowerCase().includes(query) || c.terms.some((t) => t.text.toLowerCase().includes(query))
      );
    }
    // Sort by cluster title (name) alphabetically
    return [...result].sort((a, b) => a.title.localeCompare(b.title));
  }, [clusters, searchQuery]);

  // Compute available letters from filtered clusters
  const availableLetters = useMemo(() => {
    const letters = new Set<string>();
    filteredClusters.forEach((c) => {
      const firstChar = c.title.charAt(0).toUpperCase();
      if (/[A-Z]/.test(firstChar)) {
        letters.add(firstChar);
      } else {
        letters.add("#");
      }
    });
    return letters;
  }, [filteredClusters]);

  // Track active letter via IntersectionObserver
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    // Build a map from cluster ID to its first letter
    const clusterLetterMap = new Map<string, string>();
    for (const c of filteredClusters) {
      const firstChar = c.title.charAt(0).toUpperCase();
      const letter = /[A-Z]/.test(firstChar) ? firstChar : "#";
      clusterLetterMap.set(String(c.id), letter);
    }

    // Disconnect previous observer
    observerRef.current?.disconnect();

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the topmost visible entry
        let topEntry: IntersectionObserverEntry | null = null;
        for (const entry of entries) {
          if (entry.isIntersecting) {
            if (!topEntry || entry.boundingClientRect.top < topEntry.boundingClientRect.top) {
              topEntry = entry;
            }
          }
        }
        if (topEntry) {
          const clusterId = (topEntry.target as HTMLElement).dataset.clusterId;
          if (clusterId && clusterLetterMap.has(clusterId)) {
            setActiveLetter(clusterLetterMap.get(clusterId)!);
          }
        }
      },
      { rootMargin: "-106px 0px -80% 0px", threshold: 0 }
    );

    observerRef.current = observer;

    // Observe all cluster card elements
    const elements = document.querySelectorAll("[data-cluster-id]");
    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [filteredClusters]);

  // Full alphabet for navigation
  const alphabet = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

  const scrollToLetter = (letter: string) => {
    setActiveLetter(letter);
    const cluster = filteredClusters.find((c) => {
      const firstChar = c.title.charAt(0).toUpperCase();
      if (letter === "#") {
        return !/[A-Z]/.test(firstChar);
      }
      return firstChar === letter;
    });
    if (cluster) {
      const element = document.querySelector(`[data-cluster-id="${CSS.escape(String(cluster.id))}"]`);
      element?.scrollIntoView({ behavior: "instant", block: "start" });
    }
  };

  // Calculate stats
  const stats = useMemo(
    () => ({
      totalClusters: clusters.length,
      totalTerms: clusters.reduce((sum, c) => sum + c.total_terms, 0) + unclusteredTerms.length,
      avgTermsPerCluster:
        clusters.length > 0 ? (clusters.reduce((sum, c) => sum + c.total_terms, 0) / clusters.length).toFixed(1) : "0",
      unclusteredCount: unclusteredTerms.length,
    }),
    [clusters, unclusteredTerms]
  );

  if (!datasetId) {
    return (
      <Layout>
        <div>Invalid dataset ID</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div className={styles.page}>
          {/* Header with Navigation */}
          <WorkflowPageHeader
            title="Term Clustering"
            datasetId={datasetId!}
            datasetName={datasetName}
            backButton={{
              label: "Back to Term Extraction",
              to: `/datasets/${datasetId}/records`,
              title: "Back to Term Extraction",
            }}
            forwardButton={{
              label: "Go to Concept Mapping",
              to: `/datasets/${datasetId}/mapping`,
              title: "Go to Concept Mapping",
            }}
            helpContent={
              <>
                <p>Group similar terms together to simplify mapping to standard vocabularies in the next step.</p>
                <strong>How to use:</strong>
                <ul>
                  <li>Drag terms between clusters to reorganize them</li>
                  <li>Drag one cluster onto another to merge them</li>
                  <li>Click on a cluster name to rename it</li>
                  <li>Click Auto-Cluster to automatically group similar terms</li>
                </ul>
              </>
            }
          />

          {/* Statistics and Actions */}
          <div className={styles["stats-section"]}>
            <div className={styles["stats-grid"]}>
              <StatCard label="Clusters" value={stats.totalClusters} />
              <StatCard label="Terms" value={stats.totalTerms} color="blue" />
              <StatCard label="Avg Terms per Cluster" value={stats.avgTermsPerCluster} color="green" />
              <StatCard label="Unclustered Terms" value={stats.unclusteredCount} color="orange" />
            </div>
            <div className={styles["page-actions"]}>
              <Button
                variant="outline"
                onClick={handleDownloadClusters}
                disabled={isDownloadingClusters || (clusters.length === 0 && unclusteredTerms.length === 0)}
                className={styles["download-button"]}
                title="Download term clusters in JSON format"
              >
                {isDownloadingClusters ? "Downloading..." : "Download Term Clusters"}
              </Button>
            </div>
          </div>

          {/* Toolbar */}
          <div className={styles.toolbar}>
            <div className={styles["toolbar__controls"]}>
              <Select
                options={labels.map((l) => ({ value: l, label: l }))}
                value={selectedLabel}
                onValueChange={setSelectedLabel}
                fullWidth={false}
                className={styles["label-filter"]}
              />

              <input
                type="text"
                placeholder="Search clusters..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={styles["search-input"]}
              />
              {!labelReviewed && (
                <>
                  <Button variant="outline" onClick={handleCreateCluster}>
                    <FontAwesomeIcon icon={faPlus} /> New Cluster
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleAutoClustering}
                    disabled={isAutoClustering || clusterAll.isRunning || !selectedLabel}
                  >
                    {isAutoClustering ? "Clustering..." : "Auto-Cluster Terms"}
                  </Button>
                </>
              )}
              <Button
                variant="outline"
                onClick={handleClusterAll}
                disabled={clusterAll.isRunning || isAutoClustering || labels.length === 0}
                title="Cluster every label in the dataset. Labels with reviewed clusters are skipped."
              >
                {clusterAll.isRunning ? "Clustering All…" : "Cluster All Labels"}
              </Button>
              <Button
                variant={labelReviewed ? "success" : "primary"}
                onClick={handleToggleReview}
                disabled={isTogglingReview || clusters.length === 0 || !selectedLabel}
                title={labelReviewed ? "Unmark label as reviewed" : "Mark all clusters for this label as reviewed"}
              >
                {isTogglingReview ? (
                  "Updating..."
                ) : labelReviewed ? (
                  <>
                    <FontAwesomeIcon icon={faCheck} /> Reviewed
                  </>
                ) : (
                  "Mark as Reviewed"
                )}
              </Button>
            </div>

            <div className={styles["alphabet-nav"]}>
              {alphabet.map((letter) => {
                const isActive = availableLetters.has(letter);
                return (
                  <Button
                    key={letter}
                    variant="outline"
                    className={classNames(styles["alphabet-nav__button"], {
                      [styles["alphabet-nav__button--disabled"]]: !isActive,
                      [styles["alphabet-nav__button--active"]]: isActive && activeLetter === letter,
                    })}
                    onClick={() => scrollToLetter(letter)}
                    disabled={!isActive}
                  >
                    {letter}
                  </Button>
                );
              })}
            </div>
          </div>

          {clusterAll.isRunning && (
            <div className={styles["cluster-all-progress"]}>
              <span className={styles["cluster-all-progress__label"]}>
                Clustering all labels
                {clusterAll.progress && clusterAll.progress.total > 0
                  ? `: ${clusterAll.progress.completed} / ${clusterAll.progress.total} labels`
                  : "…"}
              </span>
              <div className={styles["cluster-all-progress__bar"]}>
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

          {error && (
            <div className={styles.error}>
              {error}
              <Button variant="ghost" size="icon" onClick={() => setError(null)} aria-label="Dismiss error">
                ×
              </Button>
            </div>
          )}

          {isLoading ? (
            <div className={styles.loading}>Loading clusters...</div>
          ) : (
            <div>
              {filteredClusters.length === 0 && clusters.length === 0 ? (
                <div className={styles["empty-state"]}>
                  <h2>No clusters yet</h2>
                  <p>Get started by auto-clustering your terms for the selected label</p>
                  <Button variant="primary" size="large" onClick={handleAutoClustering} disabled={!selectedLabel}>
                    Auto-Cluster {selectedLabel || "Terms"}
                  </Button>
                </div>
              ) : (
                <div className={styles["clusters-list"]}>
                  {filteredClusters.map((cluster) => (
                    <ClusterCard
                      key={cluster.id}
                      cluster={cluster}
                      labels={labels}
                      onRename={(title) => handleRename(cluster.id, title)}
                      onDelete={() => handleDelete(cluster.id)}
                      onRemoveTerm={handleRemoveTerm}
                      isDraggingCluster={activeDragCluster !== null}
                      readOnly={labelReviewed}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
          {unclusteredTerms.length > 0 && (
            <DroppableUnclusteredArea terms={unclusteredTerms} readOnly={labelReviewed} />
          )}
          <DragOverlay>
            {activeDragTerm ? <TermOverlay term={activeDragTerm} /> : null}
            {activeDragCluster ? <ClusterOverlay cluster={activeDragCluster} /> : null}
          </DragOverlay>
          {showBackToTop && (
            <Button
              variant="ghost"
              size="icon"
              className={styles["back-to-top"]}
              onClick={scrollToTop}
              title="Back to top"
            >
              <FontAwesomeIcon icon={faArrowUp} />
            </Button>
          )}

          {/* Toast notifications */}
          <ToastContainer toasts={toast.toasts} onDismiss={toast.dismissToast} />

          {/* Confirm dialog */}
          <ConfirmDialog
            isOpen={confirmDialog.isOpen}
            title={confirmDialog.title}
            message={confirmDialog.message}
            variant={confirmDialog.variant}
            showInput={confirmDialog.showInput}
            inputPlaceholder={confirmDialog.inputPlaceholder}
            onConfirm={confirmDialog.onConfirm}
            onCancel={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
          />
        </div>
      </DndContext>
    </Layout>
  );
}
