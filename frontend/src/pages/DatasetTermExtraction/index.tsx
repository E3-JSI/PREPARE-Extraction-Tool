import React, { useEffect, useRef, useCallback, useState, useMemo } from "react";
import { useParams } from "react-router-dom";
import classNames from "classnames";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck, faChevronLeft, faChevronRight, faEllipsis, faFilter } from "@fortawesome/free-solid-svg-icons";

import Layout from "@components/Layout";
import Button from "@components/Button";
import StatCard from "@components/StatCard";
import Dropdown from "@components/Dropdown";
import ConfirmDialog from "@components/ConfirmDialog";
import { ToastContainer } from "@components/Toast/ToastContainer";
import ProgressBar from "@components/ProgressBar";
import WorkflowPageHeader from "@components/WorkflowPageHeader";
import { useRecords } from "@/hooks/useRecords";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useToast } from "@/hooks/useToast";
import { downloadDataset as downloadDatasetAPI } from "@/api";
import { getActiveModel } from "@api/monitoring";
import ActiveModelChip from "./ActiveModelChip";
import HighlightedText from "./HighlightedText";
import RecordItem from "./RecordItem";
import TermsDrawer from "./TermsDrawer";
import AnnotationSidebar from "./AnnotationSidebar";

import type { SourceTermCreate } from "@/types";

import styles from "./styles.module.css";

const TERMS_DRAWER_STORAGE_KEY = "prepare.termExtraction.termsDrawerOpen";

const DatasetTermExtraction: React.FC = () => {
  const { datasetId } = useParams<{ datasetId: string }>();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchScope, setSearchScope] = useState<"id" | "text">("id");
  const [reviewStatusFilter, setReviewStatusFilter] = useState<"all" | "reviewed" | "not_reviewed">("all");
  const [isFilterPopoverOpen, setIsFilterPopoverOpen] = useState(false);
  const [isRailCollapsed, setIsRailCollapsed] = useState(false);
  const filterPopoverRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  // Terms drawer state (persisted per user)
  const [isTermsDrawerOpen, setIsTermsDrawerOpen] = useState(
    () => localStorage.getItem(TERMS_DRAWER_STORAGE_KEY) !== "false"
  );
  const [flashedTermId, setFlashedTermId] = useState<number | null>(null);
  const flashTimeoutRef = useRef<number | null>(null);

  // Annotation state
  const [isAnnotating, setIsAnnotating] = useState(false);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [selectedAnnotation, setSelectedAnnotation] = useState<number | null>(null);

  // Focused term state (for scrolling to terms)
  const [focusedTermId, setFocusedTermId] = useState<number | null>(null);

  const toast = useToast();
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    variant?: "danger" | "warning" | "info";
  }>({ isOpen: false, title: "", message: "", onConfirm: () => {} });

  const parsedDatasetId = datasetId ? parseInt(datasetId, 10) : 0;

  // Read-only display of the GLOBAL active extraction model (selected in Monitor).
  const [activeModelName, setActiveModelName] = useState<string>("Default model");

  const {
    dataset,
    records,
    pagination,
    stats,
    selectedRecord,
    selectedRecordTerms,
    isLoading,
    isLoadingMore,
    isLoadingTerms,
    isExtractingDataset,
    isCancellingExtraction,
    extractionProgress,
    hasMore,
    error,
    loadMoreRecords,
    selectRecord,
    markRecordReviewed,
    addSourceTerm,
    removeSourceTerm,
    updateSourceTermLabel,
    updateSourceTermDate,
    addLink,
    removeLink,
    extractTermsForDataset,
    cancelDatasetExtraction,
    deleteExtractedTermsForDataset,
    fetchRecords,
    patientIdFilter,
    setPatientIdFilter,
    textFilter,
    setTextFilter,
    reviewedFilter,
    setReviewedFilter,
  } = useRecords(parsedDatasetId);

  // Update page title based on dataset name
  usePageTitle(dataset?.name ? `Term Extraction - ${dataset.name}` : "Term Extraction");

  // Debounced scoped search — one input feeds either the patient-ID or text filter
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchScope === "id") {
        setPatientIdFilter(searchQuery);
        setTextFilter("");
      } else {
        setTextFilter(searchQuery);
        setPatientIdFilter("");
      }
    }, 500); // 500ms debounce

    return () => clearTimeout(timer);
  }, [searchQuery, searchScope, setPatientIdFilter, setTextFilter]);

  // Update reviewed filter when review status changes
  useEffect(() => {
    if (reviewStatusFilter === "all") {
      setReviewedFilter(undefined);
    } else if (reviewStatusFilter === "reviewed") {
      setReviewedFilter(true);
    } else {
      setReviewedFilter(false);
    }
  }, [reviewStatusFilter, setReviewedFilter]);

  // Refetch records when filters change
  useEffect(() => {
    fetchRecords(1, 20);
  }, [patientIdFilter, textFilter, reviewedFilter, fetchRecords]);

  // Close the review-status filter popover on outside click
  useEffect(() => {
    if (!isFilterPopoverOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (filterPopoverRef.current && !filterPopoverRef.current.contains(event.target as Node)) {
        setIsFilterPopoverOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isFilterPopoverOpen]);

  // Infinite scroll observer
  useEffect(() => {
    if (!loadMoreRef.current || !hasMore || isLoadingMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMoreRecords();
        }
      },
      { threshold: 0.1 }
    );

    observer.observe(loadMoreRef.current);

    return () => observer.disconnect();
  }, [hasMore, isLoadingMore, loadMoreRecords]);

  // Auto-select first record, and re-select when the current selection is no
  // longer present in the records list (e.g. after a filter change replaces it).
  useEffect(() => {
    if (records.length === 0) return;
    const selectionStillValid = selectedRecord && records.some((r) => r.id === selectedRecord.id);
    if (!selectionStillValid) {
      selectRecord(records[0]);
    }
  }, [records, selectedRecord, selectRecord]);

  // Fetch the global active extraction model name once on mount.
  useEffect(() => {
    let cancelled = false;
    getActiveModel()
      .then((res) => {
        if (cancelled) return;
        setActiveModelName(res.active_model?.name ?? "Default model");
      })
      .catch(() => {
        /* optional; ignore */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Plain toggle, used by the annotation sidebar (no auto-advance there)
  const handleMarkReviewed = useCallback(async () => {
    if (!selectedRecord) return;
    try {
      await markRecordReviewed(selectedRecord.id, !selectedRecord.reviewed);
    } catch (err) {
      console.error("Failed to update review status:", err);
    }
  }, [selectedRecord, markRecordReviewed]);

  // Annotation handlers
  const handleOpenAnnotation = useCallback(() => {
    setIsAnnotating(true);
    // Auto-select first label if available
    if (dataset?.labels && dataset.labels.length > 0) {
      setSelectedLabel(dataset.labels[0]);
    }
  }, [dataset]);

  const handleCloseAnnotation = useCallback(() => {
    setIsAnnotating(false);
    setSelectedLabel(null);
    setSelectedAnnotation(null);
  }, []);

  const handleCreateAnnotation = useCallback(
    async (term: SourceTermCreate) => {
      try {
        await addSourceTerm(term);
      } catch (err) {
        console.error("Failed to create annotation:", err);
      }
    },
    [addSourceTerm]
  );

  const handleDeleteAnnotation = useCallback(
    async (termId: number) => {
      try {
        await removeSourceTerm(termId);
        if (selectedAnnotation === termId) {
          setSelectedAnnotation(null);
        }
      } catch (err) {
        console.error("Failed to delete annotation:", err);
      }
    },
    [removeSourceTerm, selectedAnnotation]
  );

  const handleUpdateAnnotationLabel = useCallback(
    async (termId: number, newLabel: string) => {
      try {
        await updateSourceTermLabel(termId, newLabel);
      } catch (err) {
        console.error("Failed to update annotation label:", err);
      }
    },
    [updateSourceTermLabel]
  );

  const handleUpdateAnnotationDate = useCallback(
    async (termId: number, newDate: string) => {
      try {
        // newDate expected in YYYY-MM-DD or empty string
        const payload = newDate === "" ? null : newDate;
        await updateSourceTermDate(termId, payload);
      } catch (err) {
        console.error("Failed to update annotation date:", err);
      }
    },
    [updateSourceTermDate]
  );

  const handleCreateLink = useCallback(
    async (fromTermId: number, toTermId: number) => {
      try {
        await addLink(fromTermId, toTermId);
      } catch (err) {
        console.error("Failed to create link:", err);
      }
    },
    [addLink]
  );

  const handleDeleteLink = useCallback(
    async (linkId: number) => {
      try {
        await removeLink(linkId);
      } catch (err) {
        console.error("Failed to delete link:", err);
      }
    },
    [removeLink]
  );

  // Record navigation
  const handlePreviousRecord = useCallback(() => {
    if (!selectedRecord || records.length === 0) return;

    const currentIndex = records.findIndex((r) => r.id === selectedRecord.id);

    if (currentIndex > 0) {
      selectRecord(records[currentIndex - 1]);
    }
  }, [selectedRecord, records, selectRecord]);

  const [pendingNextNavigation, setPendingNextNavigation] = useState(false);

  const handleNextRecord = useCallback(async () => {
    if (!selectedRecord || records.length === 0) return;

    const currentIndex = records.findIndex((r) => r.id === selectedRecord.id);

    if (currentIndex < records.length - 1) {
      selectRecord(records[currentIndex + 1]);
    } else if (hasMore) {
      setPendingNextNavigation(true);
      await loadMoreRecords();
    }
  }, [selectedRecord, records, selectRecord, hasMore, loadMoreRecords]);

  // Compute navigation availability
  const currentRecordIndex = useMemo(() => {
    if (!selectedRecord || records.length === 0) return -1;
    return records.findIndex((r) => r.id === selectedRecord.id);
  }, [selectedRecord, records]);

  const hasPreviousRecord = currentRecordIndex > 0;
  const hasNextRecord = currentRecordIndex >= 0 && (currentRecordIndex < records.length - 1 || hasMore);

  // Navigate to next record after loading more records via navigation
  useEffect(() => {
    if (pendingNextNavigation && !isLoadingMore && selectedRecord) {
      const currentIndex = records.findIndex((r) => r.id === selectedRecord.id);
      if (currentIndex >= 0 && currentIndex < records.length - 1) {
        selectRecord(records[currentIndex + 1]);
      }
      setPendingNextNavigation(false);
    }
  }, [pendingNextNavigation, isLoadingMore, records, selectedRecord, selectRecord]);

  // Mark reviewed from the main header: marking advances to the next unreviewed
  // record; clicking on an already-reviewed record un-marks it (re-enables editing).
  const [pendingUnreviewedAdvance, setPendingUnreviewedAdvance] = useState(false);

  const handleToggleReviewedAndAdvance = useCallback(async () => {
    if (!selectedRecord) return;
    const nextReviewed = !selectedRecord.reviewed;
    try {
      await markRecordReviewed(selectedRecord.id, nextReviewed);
    } catch (err) {
      console.error("Failed to update review status:", err);
      return;
    }
    if (!nextReviewed) return;

    const currentIndex = records.findIndex((r) => r.id === selectedRecord.id);
    const nextUnreviewed = records.slice(currentIndex + 1).find((r) => !r.reviewed);
    if (nextUnreviewed) {
      selectRecord(nextUnreviewed);
    } else if (hasMore) {
      setPendingUnreviewedAdvance(true);
      await loadMoreRecords();
    }
  }, [selectedRecord, markRecordReviewed, records, selectRecord, hasMore, loadMoreRecords]);

  // Continue the advance once more records are loaded (pages until an
  // unreviewed record is found or the list is exhausted).
  useEffect(() => {
    if (!pendingUnreviewedAdvance || isLoadingMore || !selectedRecord) return;
    const currentIndex = records.findIndex((r) => r.id === selectedRecord.id);
    const nextUnreviewed = records.slice(currentIndex + 1).find((r) => !r.reviewed);
    if (nextUnreviewed) {
      setPendingUnreviewedAdvance(false);
      selectRecord(nextUnreviewed);
    } else if (hasMore) {
      loadMoreRecords();
    } else {
      setPendingUnreviewedAdvance(false);
    }
  }, [pendingUnreviewedAdvance, isLoadingMore, records, selectedRecord, hasMore, selectRecord, loadMoreRecords]);

  // Keyboard navigation: ← / → switch records (not while typing or annotating)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (isAnnotating || confirmDialog.isOpen) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        handlePreviousRecord();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        handleNextRecord();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isAnnotating, confirmDialog.isOpen, handlePreviousRecord, handleNextRecord]);

  // Reset annotation selection when changing records
  useEffect(() => {
    setSelectedAnnotation(null);
    setFocusedTermId(null);
  }, [selectedRecord?.id]);

  // Scroll to a term in the text (from a drawer card click)
  const scrollToTerm = useCallback((termId: number) => {
    const termElement = document.querySelector(`[data-term-id="${CSS.escape(String(termId))}"]`);
    if (termElement) {
      termElement.scrollIntoView({ behavior: "smooth", block: "center" });
      setFocusedTermId(termId);
      // Remove focus highlight after animation
      setTimeout(() => setFocusedTermId(null), 2000);
    }
  }, []);

  const handleToggleTermsDrawer = useCallback((open: boolean) => {
    setIsTermsDrawerOpen(open);
    localStorage.setItem(TERMS_DRAWER_STORAGE_KEY, String(open));
  }, []);

  // Clicking a highlight in the text opens the drawer and flashes the term's card
  const handleHighlightClick = useCallback(
    (termId: number) => {
      handleToggleTermsDrawer(true);
      setFlashedTermId(termId);
      // Wait a tick so the drawer (and its card) is rendered before scrolling
      window.setTimeout(() => {
        const card = document.querySelector(`[data-drawer-term-id="${CSS.escape(String(termId))}"]`);
        card?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 50);
      if (flashTimeoutRef.current !== null) window.clearTimeout(flashTimeoutRef.current);
      flashTimeoutRef.current = window.setTimeout(() => setFlashedTermId(null), 1600);
    },
    [handleToggleTermsDrawer]
  );

  useEffect(() => {
    return () => {
      if (flashTimeoutRef.current !== null) window.clearTimeout(flashTimeoutRef.current);
    };
  }, []);

  const handleExtractTermsForDataset = useCallback(() => {
    if (!stats?.total_records) return;

    setConfirmDialog({
      isOpen: true,
      title: "Extract Terms",
      message: `This will extract terms from all ${stats.total_records} record${stats.total_records !== 1 ? "s" : ""} in the dataset using ${activeModelName}. This may take several minutes. Continue?`,
      variant: "warning",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          const result = await extractTermsForDataset();
          if (result.status === "cancelled") {
            toast.warning("Extraction was cancelled by the user");
          } else {
            toast.success("Terms extracted successfully for all records");
          }
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to extract terms");
        }
      },
    });
  }, [stats, activeModelName, extractTermsForDataset, toast]);

  const handleDeleteExtractedTerms = useCallback(() => {
    setConfirmDialog({
      isOpen: true,
      title: "Delete Extracted Terms",
      message: "This will delete all automatically extracted terms in this dataset. Continue?",
      variant: "danger",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          const res = await deleteExtractedTermsForDataset();
          toast.success(res.message || "Deleted extracted terms");
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to delete extracted terms");
        }
      },
    });
  }, [deleteExtractedTermsForDataset, toast]);

  const handleTermDownload = useCallback(async () => {
    try {
      await downloadDatasetAPI(parsedDatasetId, "gliner");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to download GLiNER file");
    }
  }, [parsedDatasetId, toast]);

  if (!parsedDatasetId) {
    return (
      <Layout>
        <div className={styles.page}>
          <div className={styles.error}>Invalid dataset ID</div>
        </div>
      </Layout>
    );
  }

  const totalRecords = stats?.total_records ?? 0;
  const reviewedRecords = totalRecords - (stats?.pending_review_count ?? totalRecords);

  const reviewedPercentage = totalRecords > 0 ? `${((reviewedRecords / totalRecords) * 100).toFixed(1)}%` : "0.0%";

  const filteredTotal = pagination?.total ?? records.length;

  return (
    <Layout>
      <div className={styles.page}>
        {/* Header with Navigation */}
        <WorkflowPageHeader
          title="Term Extraction"
          datasetId={datasetId!}
          datasetName={dataset?.name}
          backButton={{
            label: "Back to Overview",
            to: `/datasets/${datasetId}`,
            title: "Back to Dataset Overview",
          }}
          forwardButton={{
            label: "Go to Term Clustering",
            to: `/datasets/${datasetId}/clusters`,
            title: "Go to Term Clustering",
          }}
          helpContent={
            <>
              <p>Annotate the text with the appropriate labels to identify medical terms for standardization.</p>
              <strong>How to use:</strong>
              <ul>
                <li>Click Auto-Detect Terms in All Records to automatically identify terms</li>
                <li>Click Edit Labels to manually add or remove term labels</li>
                <li>Mark record as Reviewed when done — it jumps to the next unreviewed record</li>
                <li>Use ← / → or the ◀ ▶ buttons to move between records</li>
              </ul>
            </>
          }
        />

        {/* Statistics and Actions — single band */}
        <div className={styles["stats-section"]}>
          <div className={styles["stats-section__grid"]}>
            <StatCard label="Records" value={stats?.total_records ?? 0} />
            <StatCard label="Identified Terms" value={stats?.extracted_terms_count ?? 0} color="blue" />
            <StatCard label="Reviewed Records" value={reviewedPercentage} color="green" />
          </div>
          {isExtractingDataset ? (
            <div className={styles["stats-section__extraction"]}>
              <span className={styles["stats-section__extraction-label"]}>Extraction in progress</span>
              {extractionProgress && extractionProgress.total > 0 && (
                <span className={styles["stats-section__extraction-count"]}>
                  {extractionProgress.completed} / {extractionProgress.total} records
                </span>
              )}
              <div className={styles["stats-section__extraction-progress"]}>
                <ProgressBar
                  progress={
                    extractionProgress && extractionProgress.total > 0
                      ? (extractionProgress.completed / extractionProgress.total) * 100
                      : 0
                  }
                  showPercentage
                />
              </div>
              <Button
                variant="outline"
                size="small"
                onClick={cancelDatasetExtraction}
                disabled={isCancellingExtraction}
              >
                {isCancellingExtraction ? "Cancelling…" : "Cancel"}
              </Button>
            </div>
          ) : (
            <div className={styles["stats-section__actions"]}>
              <div className={styles["stats-section__actions-row"]}>
                <Button
                  variant="primary"
                  onClick={handleExtractTermsForDataset}
                  disabled={!dataset?.labels?.length}
                  title={
                    !dataset?.labels?.length ? "No labels defined for this dataset" : "Extract terms from all records"
                  }
                >
                  Auto-Detect Terms in All Records
                </Button>
                <Dropdown
                  align="right"
                  trigger={
                    <Button variant="outline" size="icon" title="More actions">
                      <FontAwesomeIcon icon={faEllipsis} />
                    </Button>
                  }
                  items={[
                    {
                      label: "Download Term Dataset",
                      onClick: handleTermDownload,
                      disabled: totalRecords === 0,
                      title:
                        totalRecords === 0
                          ? "No records in this dataset"
                          : "Download all extracted terms in JSON format (used for NER training)",
                    },
                    {
                      label: "Delete Auto-Extracted Terms…",
                      onClick: handleDeleteExtractedTerms,
                      variant: "danger",
                      title: "Delete all automatically extracted terms",
                    },
                  ]}
                />
              </div>
              <ActiveModelChip modelName={activeModelName} />
            </div>
          )}
        </div>

        {error && <div className={styles.error}>{error}</div>}

        {/* Main Content */}
        <div className={classNames(styles.content, { [styles["content--rail-collapsed"]]: isRailCollapsed })}>
          {/* Records Rail */}
          <aside
            className={classNames(styles["records-panel"], {
              [styles["records-panel--collapsed"]]: isRailCollapsed,
            })}
          >
            {isRailCollapsed ? (
              <button
                className={styles["records-panel__expand"]}
                onClick={() => setIsRailCollapsed(false)}
                title="Expand records list"
              >
                Records ({filteredTotal})
              </button>
            ) : (
              <>
                <div className={styles["records-panel__header"]}>
                  <div className={styles["records-panel__title-row"]}>
                    <h2 className={styles["records-panel__title"]}>
                      Records <span className={styles["records-panel__count"]}>({filteredTotal})</span>
                    </h2>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setIsRailCollapsed(true)}
                      title="Collapse records list"
                    >
                      <FontAwesomeIcon icon={faChevronLeft} />
                    </Button>
                  </div>
                  <div className={styles["records-panel__search-row"]}>
                    <div className={styles["records-panel__search-box"]}>
                      <select
                        className={styles["records-panel__scope"]}
                        value={searchScope}
                        onChange={(e) => setSearchScope(e.target.value as "id" | "text")}
                        title="Search by patient ID or record text"
                      >
                        <option value="id">ID</option>
                        <option value="text">Text</option>
                      </select>
                      <input
                        type="text"
                        className={styles["records-panel__search"]}
                        placeholder="Search…"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                      />
                    </div>
                    <div className={styles["records-panel__filter"]} ref={filterPopoverRef}>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => setIsFilterPopoverOpen((open) => !open)}
                        title="Filter by review status"
                      >
                        <FontAwesomeIcon icon={faFilter} />
                      </Button>
                      {reviewStatusFilter !== "all" && <span className={styles["records-panel__filter-dot"]} />}
                      {isFilterPopoverOpen && (
                        <div className={styles["records-panel__filter-pop"]}>
                          <label>
                            <input
                              type="radio"
                              name="reviewStatus"
                              value="all"
                              checked={reviewStatusFilter === "all"}
                              onChange={(e) => setReviewStatusFilter(e.target.value as "all")}
                            />
                            <span>All</span>
                          </label>
                          <label>
                            <input
                              type="radio"
                              name="reviewStatus"
                              value="reviewed"
                              checked={reviewStatusFilter === "reviewed"}
                              onChange={(e) => setReviewStatusFilter(e.target.value as "reviewed")}
                            />
                            <span>Reviewed</span>
                          </label>
                          <label>
                            <input
                              type="radio"
                              name="reviewStatus"
                              value="not_reviewed"
                              checked={reviewStatusFilter === "not_reviewed"}
                              onChange={(e) => setReviewStatusFilter(e.target.value as "not_reviewed")}
                            />
                            <span>Not Reviewed</span>
                          </label>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
                <div className={styles["records-panel__list"]}>
                  {isLoading ? (
                    <div className={styles.loading}>Loading records...</div>
                  ) : records.length === 0 ? (
                    <div className={styles["empty-state"]}>
                      <div className={styles["empty-state__icon"]}>📄</div>
                      <p className={styles["empty-state__text"]}>
                        {searchQuery || reviewStatusFilter !== "all" ? "No matching records" : "No records yet"}
                      </p>
                    </div>
                  ) : (
                    <>
                      {records.map((record) => (
                        <RecordItem
                          key={record.id}
                          record={record}
                          isSelected={selectedRecord?.id === record.id}
                          onClick={() => selectRecord(record)}
                        />
                      ))}
                      {hasMore && <div ref={loadMoreRef} className={styles["load-more-trigger"]} />}
                      {isLoadingMore && <div className={styles["loading-more"]}>Loading more records...</div>}
                    </>
                  )}
                </div>
              </>
            )}
          </aside>

          {/* NER View */}
          <div className={styles["record-text-panel"]}>
            {selectedRecord ? (
              <>
                <div className={styles["record-text-panel__header"]}>
                  <div className={styles["record-text-panel__pager"]}>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={handlePreviousRecord}
                      disabled={!hasPreviousRecord}
                      title="Previous record (←)"
                    >
                      <FontAwesomeIcon icon={faChevronLeft} />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={handleNextRecord}
                      disabled={!hasNextRecord}
                      title="Next record (→)"
                    >
                      <FontAwesomeIcon icon={faChevronRight} />
                    </Button>
                  </div>
                  <h2 className={styles["record-text-panel__info"]}>
                    {selectedRecord.patient_id}
                    {selectedRecord.seq_number && ` · #${selectedRecord.seq_number}`}
                    {currentRecordIndex >= 0 && (
                      <span className={styles["record-text-panel__info-count"]}>
                        {` · record ${currentRecordIndex + 1} / ${filteredTotal}`}
                      </span>
                    )}
                  </h2>
                  <div className={styles["record-text-panel__actions"]}>
                    <Button
                      variant="outline"
                      size="small"
                      className={classNames({
                        [styles["record-text-panel__terms-toggle--active"]]: isTermsDrawerOpen,
                      })}
                      onClick={() => handleToggleTermsDrawer(!isTermsDrawerOpen)}
                      title={isTermsDrawerOpen ? "Hide extracted terms" : "Show extracted terms"}
                    >
                      Terms ({selectedRecordTerms.length})
                    </Button>
                    <Button
                      variant="outline"
                      size="small"
                      onClick={handleOpenAnnotation}
                      disabled={selectedRecord.reviewed}
                      title={selectedRecord.reviewed ? "Unmark as reviewed to edit labels" : "Edit Labels"}
                    >
                      Edit Labels
                    </Button>
                    <Button
                      variant={selectedRecord.reviewed ? "success" : "primary"}
                      size="small"
                      onClick={handleToggleReviewedAndAdvance}
                      title={
                        selectedRecord.reviewed
                          ? "Unmark as reviewed to edit this record again"
                          : "Mark reviewed and jump to the next unreviewed record"
                      }
                    >
                      {selectedRecord.reviewed ? <FontAwesomeIcon icon={faCheck} /> : null}
                      <span className={styles["record-navigation__review-text"]}>
                        {selectedRecord.reviewed ? "Reviewed" : "Mark Reviewed ▸"}
                      </span>
                    </Button>
                  </div>
                </div>
                <div className={styles["record-text-panel__body"]}>
                  <div className={styles["record-text-panel__content"]}>
                    {isLoadingTerms ? (
                      <div className={styles.loading}>Loading...</div>
                    ) : (
                      <HighlightedText
                        text={selectedRecord.text}
                        terms={selectedRecordTerms}
                        labels={dataset?.labels ?? []}
                        focusedTermId={focusedTermId}
                        onTermClick={handleHighlightClick}
                      />
                    )}
                  </div>
                  <TermsDrawer
                    isOpen={isTermsDrawerOpen}
                    onToggle={handleToggleTermsDrawer}
                    terms={selectedRecordTerms}
                    labels={dataset?.labels ?? []}
                    flashedTermId={flashedTermId}
                    onTermClick={scrollToTerm}
                  />
                </div>
              </>
            ) : (
              <div className={styles["empty-state"]}>
                <p className={styles["empty-state__text"]}>Select a record to view details</p>
              </div>
            )}
          </div>
        </div>

        {/* Annotation Sidebar */}
        <AnnotationSidebar
          isOpen={isAnnotating}
          text={selectedRecord?.text ?? ""}
          labels={dataset?.labels ?? []}
          labelRelations={dataset?.label_relations ?? []}
          selectedLabel={selectedLabel}
          onSelectLabel={setSelectedLabel}
          annotations={selectedRecordTerms}
          selectedAnnotation={selectedAnnotation}
          onSelectAnnotation={setSelectedAnnotation}
          onCreateAnnotation={handleCreateAnnotation}
          onDeleteAnnotation={handleDeleteAnnotation}
          onUpdateAnnotationLabel={handleUpdateAnnotationLabel}
          onUpdateAnnotationDate={handleUpdateAnnotationDate}
          onCreateLink={handleCreateLink}
          onDeleteLink={handleDeleteLink}
          onClose={handleCloseAnnotation}
          onPreviousRecord={handlePreviousRecord}
          onNextRecord={handleNextRecord}
          hasPreviousRecord={hasPreviousRecord}
          hasNextRecord={hasNextRecord}
          onMarkReviewed={handleMarkReviewed}
          isReviewed={selectedRecord?.reviewed ?? false}
          readOnly={selectedRecord?.reviewed ?? false}
          recordInfo={
            selectedRecord
              ? `Patient ${selectedRecord.patient_id}${selectedRecord.seq_number ? ` · #${selectedRecord.seq_number}` : ""}`
              : undefined
          }
        />

        {/* Toast notifications */}
        <ToastContainer toasts={toast.toasts} onDismiss={toast.dismissToast} />

        {/* Confirm dialog */}
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

export default DatasetTermExtraction;
