import React, { useEffect, useRef, useCallback, useState, useMemo } from "react";
import { useParams } from "react-router-dom";
import classNames from "classnames";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck } from "@fortawesome/free-solid-svg-icons";

import Layout from "@components/Layout";
import Button from "@components/Button";
import StatCard from "@components/StatCard";
import ConfirmDialog from "@components/ConfirmDialog";
import { ToastContainer } from "@components/Toast/ToastContainer";
import ProgressBar from "@/components/ProgressBar/index";
import WorkflowPageHeader from "@components/WorkflowPageHeader";
import { useRecords } from "@/hooks/useRecords";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useToast } from "@/hooks/useToast";
import { getLabelColorClass } from "@/utils/labelColors";
import { downloadDataset as downloadDatasetAPI } from "@/api";
import HighlightedText from "./HighlightedText";
import RecordItem from "./RecordItem";
import AnnotationSidebar from "./AnnotationSidebar";

import type { SourceTermCreate } from "@/types";

import styles from "./styles.module.css";

const DatasetTermExtraction: React.FC = () => {
  const { datasetId } = useParams<{ datasetId: string }>();
  const [searchQuery, setSearchQuery] = useState("");
  const [patientIdQuery, setPatientIdQuery] = useState("");
  const [reviewStatusFilter, setReviewStatusFilter] = useState<"all" | "reviewed" | "not_reviewed">("all");
  const loadMoreRef = useRef<HTMLDivElement>(null);

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

  const {
    dataset,
    records,
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

  // Debounced search - update filters after user stops typing
  useEffect(() => {
    const timer = setTimeout(() => {
      setTextFilter(searchQuery);
    }, 500); // 500ms debounce

    return () => clearTimeout(timer);
  }, [searchQuery, setTextFilter]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setPatientIdFilter(patientIdQuery);
    }, 500); // 500ms debounce

    return () => clearTimeout(timer);
  }, [patientIdQuery, setPatientIdFilter]);

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

  // Auto-select first record
  useEffect(() => {
    if (records.length > 0 && !selectedRecord) {
      selectRecord(records[0]);
    }
  }, [records, selectedRecord, selectRecord]);

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

  // Navigation handlers for annotation sidebar
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

  // Reset annotation selection when changing records
  useEffect(() => {
    setSelectedAnnotation(null);
    setFocusedTermId(null);
  }, [selectedRecord?.id]);

  // Scroll to a term in the text
  const scrollToTerm = useCallback((termId: number) => {
    const termElement = document.querySelector(`[data-term-id="${CSS.escape(String(termId))}"]`);
    if (termElement) {
      termElement.scrollIntoView({ behavior: "smooth", block: "center" });
      setFocusedTermId(termId);
      // Remove focus highlight after animation
      setTimeout(() => setFocusedTermId(null), 2000);
    }
  }, []);

  const handleExtractTermsForDataset = useCallback(() => {
    if (!stats?.total_records) return;

    setConfirmDialog({
      isOpen: true,
      title: "Extract Terms",
      message: `This will extract terms from all ${stats.total_records} record${stats.total_records !== 1 ? "s" : ""} in the dataset. This may take several minutes. Continue?`,
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
  }, [stats, extractTermsForDataset, toast]);

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
                <li>Mark record as Reviewed when done</li>
                <li>Use filters to find specific records</li>
              </ul>
            </>
          }
        />

        {/* Statistics and Actions */}
        <div className={styles["stats-section"]}>
          <div className={styles["stats-section__grid"]}>
            <StatCard label="Records" value={stats?.total_records ?? 0} />
            <StatCard label="Identified Terms" value={stats?.extracted_terms_count ?? 0} color="blue" />
            <StatCard label="Reviewed Records" value={reviewedPercentage} color="green" />
          </div>
          <div className={styles["stats-section__actions"]}>
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
              <>
                <Button
                  variant="outline"
                  onClick={handleTermDownload}
                  disabled={totalRecords === 0}
                  title={
                    totalRecords === 0
                      ? "No records in this dataset"
                      : "Download all extracted terms in JSON format (used for NER training)"
                  }
                >
                  Download Term Dataset
                </Button>
                <Button
                  variant="outline"
                  onClick={handleExtractTermsForDataset}
                  disabled={!dataset?.labels?.length}
                  title={
                    !dataset?.labels?.length ? "No labels defined for this dataset" : "Extract terms from all records"
                  }
                >
                  Auto-Detect Terms in All Records
                </Button>
                <Button
                  variant="danger"
                  onClick={handleDeleteExtractedTerms}
                  title="Delete all automatically extracted terms"
                >
                  Delete Auto-Extracted Terms
                </Button>
              </>
            )}
          </div>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        {/* Main Content */}
        <div className={styles.content}>
          {/* Records List Panel */}
          <div className={styles["records-panel"]}>
            <div className={styles["records-panel__header"]}>
              <h2 className={styles["records-panel__title"]}>Records List</h2>
              <input
                type="text"
                className={styles["records-panel__search"]}
                placeholder="Search by patient ID..."
                value={patientIdQuery}
                onChange={(e) => setPatientIdQuery(e.target.value)}
              />
              <input
                type="text"
                className={styles["records-panel__search"]}
                placeholder="Search by text..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />

              <div className={styles["records-panel__filters"]}>
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
            </div>
            <div className={styles["records-panel__list"]}>
              {isLoading ? (
                <div className={styles.loading}>Loading records...</div>
              ) : records.length === 0 ? (
                <div className={styles["empty-state"]}>
                  <div className={styles["empty-state__icon"]}>📄</div>
                  <p className={styles["empty-state__text"]}>
                    {searchQuery || patientIdQuery || reviewStatusFilter !== "all"
                      ? "No matching records"
                      : "No records yet"}
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
          </div>

          {/* Detail Panels */}
          <div className={styles["detail-panels"]}>
            {selectedRecord ? (
              <>
                {/* Record Text Panel */}
                <div className={styles["record-text-panel"]}>
                  <div className={styles["record-text-panel__header"]}>
                    <h2 className={styles["record-text-panel__title"]}>NER View</h2>
                    <div className={styles["record-text-panel__actions"]}>
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
                        onClick={handleMarkReviewed}
                      >
                        {selectedRecord.reviewed ? <FontAwesomeIcon icon={faCheck} /> : null}
                        <span className={styles["record-navigation__review-text"]}>
                          {selectedRecord.reviewed ? "Reviewed" : "Mark as Reviewed"}
                        </span>
                      </Button>
                    </div>
                  </div>
                  <div className={styles["record-text-panel__header"]}>
                    <h3 className={styles["record-text-panel__title"]}>
                      Patient ID: {selectedRecord.patient_id}
                      {selectedRecord.seq_number && ` | #${selectedRecord.seq_number}`}
                    </h3>
                  </div>
                  <div className={styles["record-text-panel__content"]}>
                    {isLoadingTerms ? (
                      <div className={styles.loading}>Loading...</div>
                    ) : (
                      <HighlightedText
                        text={selectedRecord.text}
                        terms={selectedRecordTerms}
                        labels={dataset?.labels ?? []}
                        focusedTermId={focusedTermId}
                      />
                    )}
                  </div>
                </div>

                {/* Extracted Terms Panel */}
                <div className={styles["terms-panel"]}>
                  <div className={styles["terms-panel__header"]}>
                    <h2 className={styles["terms-panel__title"]}>Extracted Terms ({selectedRecordTerms.length})</h2>
                  </div>
                  <div className={styles["terms-panel__content"]}>
                    {selectedRecordTerms.length === 0 ? (
                      <div className={styles["empty-state"]}>
                        <p className={styles["empty-state__text"]}>No terms extracted</p>
                        <p className={styles["empty-state__subtext"]}>Run NER extraction to identify terms</p>
                      </div>
                    ) : (
                      <div className={styles["terms-list"]}>
                        {selectedRecordTerms.map((term) => (
                          <div key={term.id} className={styles["term-item"]} onClick={() => scrollToTerm(term.id)}>
                            <div className={styles["term-item__info"]}>
                              <span className={styles["term-item__value"]}>{term.value}</span>
                              <span
                                className={classNames(
                                  styles["term-item__label"],
                                  styles[getLabelColorClass(term.label, dataset?.labels ?? [])]
                                )}
                              >
                                {term.label}
                              </span>
                              <span className={styles["term-item__date"]}>
                                {term.linked_visit_date
                                  ? new Date(term.linked_visit_date).toLocaleDateString("en-GB", {
                                      day: "2-digit",
                                      month: "2-digit",
                                      year: "numeric",
                                    })
                                  : "No date"}
                              </span>
                              {term.linked_date_term_id &&
                                (() => {
                                  const dateTerm = selectedRecordTerms.find((t) => t.id === term.linked_date_term_id);
                                  if (!dateTerm) return null;
                                  return (
                                    <span className={styles["annotation-item__date-id"]}>
                                      ↳ linked to {dateTerm.value}
                                    </span>
                                  );
                                })()}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className={styles["record-text-panel"]}>
                <div className={styles["empty-state"]}>
                  <p className={styles["empty-state__text"]}>Select a record to view details</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Annotation Sidebar */}
        <AnnotationSidebar
          isOpen={isAnnotating}
          text={selectedRecord?.text ?? ""}
          labels={dataset?.labels ?? []}
          selectedLabel={selectedLabel}
          onSelectLabel={setSelectedLabel}
          annotations={selectedRecordTerms}
          selectedAnnotation={selectedAnnotation}
          onSelectAnnotation={setSelectedAnnotation}
          onCreateAnnotation={handleCreateAnnotation}
          onDeleteAnnotation={handleDeleteAnnotation}
          onUpdateAnnotationLabel={handleUpdateAnnotationLabel}
          onUpdateAnnotationDate={handleUpdateAnnotationDate}
          onClose={handleCloseAnnotation}
          onPreviousRecord={handlePreviousRecord}
          onNextRecord={handleNextRecord}
          hasPreviousRecord={hasPreviousRecord}
          hasNextRecord={hasNextRecord}
          onMarkReviewed={handleMarkReviewed}
          isReviewed={selectedRecord?.reviewed ?? false}
          readOnly={selectedRecord?.reviewed ?? false}
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
