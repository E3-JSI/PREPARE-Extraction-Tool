import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { useParams } from "react-router-dom";

import Layout from "@components/Layout";
import Button from "@components/Button";
import StatCard from "@components/StatCard";
import ConfirmDialog from "@components/ConfirmDialog";
import ProgressBar from "@components/ProgressBar";
import { ToastContainer } from "@components/Toast/ToastContainer";
import WorkflowPageHeader from "@components/WorkflowPageHeader";
import { usePageTitle } from "@hooks/usePageTitle";
import { useToast } from "@hooks/useToast";
import { useAutoMapJob, type AutoMapJobProgress } from "@hooks/useAutoMapJob";
import * as api from "@/api";

import SourceTermsTable from "./SourceTermsTable";
import SearchFiltersPanel from "./SearchFiltersPanel";
import TargetConceptsList from "./TargetConceptsList";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faArrowRightLong } from "@fortawesome/free-solid-svg-icons";

import type { ClusterMapping, ConceptSearchResult, Vocabulary, AutoMapRequest, PaginationMetadata } from "@/types";

import styles from "./styles.module.css";

export default function DatasetConceptMapping() {
  const { datasetId } = useParams<{ datasetId: string }>();

  const [datasetName, setDatasetName] = useState<string>("");
  const [mappings, setMappings] = useState<ClusterMapping[]>([]);
  const [vocabularies, setVocabularies] = useState<Vocabulary[]>([]);
  const [selectedMapping, setSelectedMapping] = useState<ClusterMapping | null>(null);
  const [searchResults, setSearchResults] = useState<ConceptSearchResult[]>([]);
  const [selectedVocabularies, setSelectedVocabularies] = useState<number[]>([]);
  const [selectedLabel, setSelectedLabel] = useState<string>("");
  const [labels, setLabels] = useState<string[]>([]);
  const [labelsLoaded, setLabelsLoaded] = useState(false);
  const [domainFilter, setDomainFilter] = useState<string>("");
  const [conceptClassFilter, setConceptClassFilter] = useState<string>("");
  const [standardOnly, setStandardOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [useSourceTerm, setUseSourceTerm] = useState(true);
  const [comment, setComment] = useState("");
  const [includeSourceTerms, setIncludeSourceTerms] = useState(false);

  // Search pagination state
  const [searchPage, setSearchPage] = useState(1);
  const [searchPagination, setSearchPagination] = useState<PaginationMetadata | null>(null);
  const [sortBy, setSortBy] = useState<"relevance" | "name" | "domain">("relevance");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  // Filter enabled states
  const [vocabularyFilterEnabled, setVocabularyFilterEnabled] = useState(false);
  const [domainFilterEnabled, setDomainFilterEnabled] = useState(false);
  const [conceptClassFilterEnabled, setConceptClassFilterEnabled] = useState(false);

  // Filter options (fetched from API)
  const [domains, setDomains] = useState<string[]>([]);
  const [conceptClasses, setConceptClasses] = useState<string[]>([]);

  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const hasLoadedOnce = useRef(false);
  // Monotonic id to discard out-of-order/stale search responses, plus a mounted
  // flag so late responses never setState after unmount.
  const searchRequestId = useRef(0);
  const isMountedRef = useRef(true);
  const [isSearching, setIsSearching] = useState(false);
  const [isMapping, setIsMapping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toast = useToast();
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    variant?: "danger" | "warning" | "info";
  }>({ isOpen: false, title: "", message: "", onConfirm: () => {} });

  usePageTitle(datasetName ? `Concept Mapping - ${datasetName}` : "Concept Mapping");

  // Track mount status so async searches can't setState after unmount.
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Fetch dataset info
  useEffect(() => {
    const fetchDataset = async () => {
      if (!datasetId) return;
      try {
        const data = await api.getDataset(parseInt(datasetId));
        setDatasetName(data.dataset.name);
        const valueLabels = new Set(data.dataset.label_relations.map((r: { to_label: string }) => r.to_label));
        const filteredLabels = data.dataset.labels.filter((l: string) => !valueLabels.has(l));
        setLabels(filteredLabels);
        if (filteredLabels.length > 0) {
          setSelectedLabel(filteredLabels[0]);
        }
        setLabelsLoaded(true);
      } catch (err) {
        console.error("Failed to fetch dataset:", err);
      }
    };
    fetchDataset();
  }, [datasetId]);

  // Fetch vocabularies
  useEffect(() => {
    const fetchVocabularies = async () => {
      try {
        const data = await api.getVocabularies(1, 100);
        setVocabularies(data.vocabularies);
        setSelectedVocabularies(data.vocabularies.map((v) => v.id));
      } catch (err) {
        console.error("Failed to fetch vocabularies:", err);
      }
    };
    fetchVocabularies();
  }, []);

  // Fetch filter options (domains and concept classes)
  useEffect(() => {
    const fetchFilterOptions = async () => {
      try {
        const [domainsResult, classesResult] = await Promise.all([
          api.getDistinctDomains(),
          api.getDistinctConceptClasses(),
        ]);
        setDomains(domainsResult.values);
        setConceptClasses(classesResult.values);
      } catch (err) {
        console.error("Failed to fetch filter options:", err);
      }
    };
    fetchFilterOptions();
  }, []);

  // Fetch mappings
  const fetchMappings = useCallback(async (): Promise<ClusterMapping[]> => {
    if (!datasetId || !labelsLoaded) return [];

    try {
      if (!hasLoadedOnce.current) {
        setIsLoading(true);
      } else {
        setIsRefreshing(true);
      }
      setError(null);
      const data = await api.getDatasetMappings(parseInt(datasetId), selectedLabel || undefined);
      setMappings(data.mappings);
      hasLoadedOnce.current = true;
      return data.mappings;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load mappings");
      return [];
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [datasetId, selectedLabel, labelsLoaded]);

  // Sync comment field when the selected mapping changes. Depend on the comment
  // too: after mapping/approving, selectedMapping is replaced with the same
  // cluster_id but an updated comment, which would otherwise leave a stale input.
  useEffect(() => {
    setComment(selectedMapping?.comment ?? "");
  }, [selectedMapping?.cluster_id, selectedMapping?.comment]);

  // Reset view when label changes
  useEffect(() => {
    hasLoadedOnce.current = false;
    setSelectedMapping(null);
    setSearchResults([]);
    setSearchPagination(null);
    setSearchQuery("");
    setSearchPage(1);
  }, [selectedLabel]);

  useEffect(() => {
    fetchMappings();
  }, [fetchMappings]);

  // Handle auto-search
  const handleAutoSearch = useCallback(async () => {
    if (!selectedMapping || !datasetId) return;

    // Use all vocabularies if filter is disabled, otherwise use selected
    const vocabIdsToUse = vocabularyFilterEnabled ? selectedVocabularies : vocabularies.map((v) => v.id);
    if (vocabIdsToUse.length === 0) return;

    // Only the latest in-flight search may apply its result.
    const requestId = ++searchRequestId.current;
    const isStale = () => !isMountedRef.current || requestId !== searchRequestId.current;

    try {
      setIsSearching(true);
      const request: AutoMapRequest = {
        vocabulary_ids: vocabIdsToUse,
        use_cluster_terms: !includeSourceTerms,
        domain_id: domainFilterEnabled && domainFilter ? domainFilter : undefined,
        concept_class_id: conceptClassFilterEnabled && conceptClassFilter ? conceptClassFilter : undefined,
        standard_concept: standardOnly ? "S" : undefined,
        search_type: "vector",
      };

      const results = await api.autoMapCluster(parseInt(datasetId), selectedMapping.cluster_id, request);
      if (isStale()) return;
      setSearchResults(results.results);
    } catch (err) {
      if (isStale()) return;
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      if (!isStale()) setIsSearching(false);
    }
  }, [
    selectedMapping,
    datasetId,
    vocabularyFilterEnabled,
    selectedVocabularies,
    vocabularies,
    domainFilterEnabled,
    domainFilter,
    conceptClassFilterEnabled,
    conceptClassFilter,
    standardOnly,
    includeSourceTerms,
  ]);

  // Handle manual search
  const handleManualSearch = useCallback(
    async (page = 1) => {
      if (!searchQuery) return;

      // Use all vocabularies if filter is disabled, otherwise use selected
      const vocabIdsToUse = vocabularyFilterEnabled ? selectedVocabularies : vocabularies.map((v) => v.id);
      if (vocabIdsToUse.length === 0) return;

      const limit = 10;
      const offset = (page - 1) * limit;

      // Only the latest in-flight search may apply its result.
      const requestId = ++searchRequestId.current;
      const isStale = () => !isMountedRef.current || requestId !== searchRequestId.current;

      try {
        setIsSearching(true);
        const results = await api.searchConcepts({
          query: searchQuery,
          vocabulary_ids: vocabIdsToUse,
          domain_id: domainFilterEnabled && domainFilter ? domainFilter : undefined,
          concept_class_id: conceptClassFilterEnabled && conceptClassFilter ? conceptClassFilter : undefined,
          standard_concept: standardOnly ? "S" : undefined,
          search_type: "hybrid",
          limit,
          offset,
          sort_by: sortBy,
          sort_order: sortOrder,
        });

        if (isStale()) return;
        setSearchResults(results.results);
        setSearchPagination(results.pagination || null);
        setSearchPage(page);
      } catch (err) {
        if (isStale()) return;
        setError(err instanceof Error ? err.message : "Search failed");
      } finally {
        if (!isStale()) setIsSearching(false);
      }
    },
    [
      searchQuery,
      vocabularyFilterEnabled,
      selectedVocabularies,
      vocabularies,
      domainFilterEnabled,
      domainFilter,
      conceptClassFilterEnabled,
      conceptClassFilter,
      standardOnly,
      sortBy,
      sortOrder,
    ]
  );

  // Single search-trigger effect: runs on cluster selection and whenever a
  // filter / query mode changes. Previously a second effect also fired
  // handleAutoSearch on selection, double-firing the request; consolidated here.
  useEffect(() => {
    if (!selectedMapping) return;
    if (useSourceTerm) {
      handleAutoSearch();
      return;
    }
    if (!searchQuery) return;

    // Debounce the custom-query search so typing doesn't fire a request per
    // keystroke. Request-sequencing inside handleManualSearch still discards
    // any out-of-order/stale responses.
    const timer = setTimeout(() => {
      handleManualSearch(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [selectedMapping, useSourceTerm, handleAutoSearch, handleManualSearch, searchQuery]);

  // Handle search (triggered by Enter key or search button)
  const handleSearch = () => {
    setSearchPage(1);
    if (useSourceTerm) {
      handleAutoSearch();
    } else {
      handleManualSearch(1);
    }
  };

  // Handle page change for manual search
  const handleSearchPageChange = (page: number) => {
    if (!useSourceTerm) {
      handleManualSearch(page);
    }
  };

  // Handle sort change — re-search triggers automatically via handleManualSearch dep on sortBy/sortOrder
  const handleSortChange = (newSortBy: "relevance" | "name" | "domain") => {
    const newOrder = sortBy === newSortBy && sortOrder === "desc" ? "asc" : "desc";
    setSortBy(newSortBy);
    setSortOrder(newOrder);
  };

  // Handle map cluster to concept
  const handleMapConcept = async (conceptId: number, status: "pending" | "approved" | "rejected" = "pending") => {
    if (!selectedMapping || !datasetId) return;

    try {
      setIsMapping(true);
      await api.mapClusterToConcept(parseInt(datasetId), selectedMapping.cluster_id, {
        concept_id: conceptId,
        status,
        comment: comment || undefined,
      });
      const freshMappings = await fetchMappings();
      toast.success(status === "approved" ? "Mapping approved" : "Concept mapped successfully");
      setComment("");

      const updated = freshMappings.find((m) => m.cluster_id === selectedMapping.cluster_id);
      if (updated) {
        setSelectedMapping(updated);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Mapping failed");
    } finally {
      setIsMapping(false);
    }
  };

  // Handle delete mapping
  const handleDeleteMapping = () => {
    if (!selectedMapping || !datasetId || !selectedMapping.concept_id) return;

    setConfirmDialog({
      isOpen: true,
      title: "Remove Mapping",
      message: "Are you sure you want to remove this mapping?",
      variant: "danger",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          await api.deleteClusterMapping(parseInt(datasetId), selectedMapping.cluster_id);
          const freshMappings = await fetchMappings();
          toast.success("Mapping removed successfully");

          const updated = freshMappings.find((m) => m.cluster_id === selectedMapping.cluster_id);
          if (updated) {
            setSelectedMapping(updated);
          }
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to delete mapping");
        }
      },
    });
  };

  // Handle approve from table row
  const handleApproveFromTable = (mapping: ClusterMapping) => {
    if (!mapping.concept_id || !datasetId) return;

    const doApprove = async () => {
      try {
        setIsMapping(true);
        await api.mapClusterToConcept(parseInt(datasetId), mapping.cluster_id, {
          concept_id: mapping.concept_id!,
          status: "approved",
        });
        const freshMappings = await fetchMappings();
        toast.success("Mapping approved");

        if (selectedMapping?.cluster_id === mapping.cluster_id) {
          const updated = freshMappings.find((m) => m.cluster_id === mapping.cluster_id);
          if (updated) setSelectedMapping(updated);
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Approval failed");
      } finally {
        setIsMapping(false);
      }
    };
    doApprove();
  };

  // Handle delete from table row
  const handleDeleteFromTable = (mapping: ClusterMapping) => {
    if (!mapping.concept_id || !datasetId) return;

    setConfirmDialog({
      isOpen: true,
      title: "Remove Mapping",
      message: `Remove mapping for "${mapping.cluster_title}"?`,
      variant: "danger",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          await api.deleteClusterMapping(parseInt(datasetId), mapping.cluster_id);
          await fetchMappings();
          toast.success("Mapping removed successfully");
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Failed to delete mapping");
        }
      },
    });
  };

  // Auto-map-all runs as a polled backend job. Completion (explicit run or a
  // resumed job) toasts the final counts and refreshes the mappings.
  const handleAutoMapComplete = useCallback(
    (p: AutoMapJobProgress) => {
      if (p.status === "cancelled") {
        toast.info(`Auto-mapping cancelled. Mapped: ${p.mapped_count}, Failed: ${p.failed_count}`);
      } else {
        toast.success(`Auto-mapping complete! Mapped: ${p.mapped_count}, Failed: ${p.failed_count}`);
      }
      fetchMappings();
    },
    [toast, fetchMappings]
  );

  const {
    isRunning: isAutoMapping,
    isCancelling: isCancellingAutoMap,
    progress: autoMapProgress,
    startAutoMap,
    cancelAutoMap,
  } = useAutoMapJob(datasetId ? parseInt(datasetId) : 0, handleAutoMapComplete);

  // Handle auto-map all
  const handleAutoMapAll = () => {
    // Use all vocabularies if filter is disabled, otherwise use selected
    const vocabIdsToUse = vocabularyFilterEnabled ? selectedVocabularies : vocabularies.map((v) => v.id);
    if (!datasetId || vocabIdsToUse.length === 0) return;

    const unmappedCount = mappings.filter((m) => m.status === "unmapped").length;

    setConfirmDialog({
      isOpen: true,
      title: "Auto-Map All Unmapped",
      message: `Auto-map ${unmappedCount} unmapped clusters? Already accepted or pending mappings will not be overridden.`,
      variant: "warning",
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        try {
          await startAutoMap({
            vocabulary_ids: vocabIdsToUse,
            label: selectedLabel || undefined,
            use_cluster_terms: true,
            search_type: "vector",
          });
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Auto-mapping failed");
        }
      },
    });
  };

  const handleCancelAutoMap = async () => {
    try {
      await cancelAutoMap();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel auto-mapping");
    }
  };

  // Handle export
  const handleExport = async () => {
    if (!datasetId) return;

    try {
      await api.exportMappings(parseInt(datasetId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    }
  };

  // Calculate stats
  const stats = useMemo(() => {
    const total = mappings.length;
    const mapped = mappings.filter((m) => m.status !== "unmapped").length;
    const unmapped = total - mapped;
    const approved = mappings.filter((m) => m.status === "approved").length;
    const mappedPercentage = total > 0 ? Math.round((mapped / total) * 100) : 0;

    return { total, mapped, unmapped, approved, mappedPercentage };
  }, [mappings]);

  if (!datasetId) {
    return (
      <Layout>
        <div>Invalid dataset ID</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className={styles.page}>
        {/* Header with Navigation */}
        <WorkflowPageHeader
          title="Concept Mapping"
          datasetId={datasetId!}
          datasetName={datasetName}
          backButton={{
            label: "Back to Term Clustering",
            to: `/datasets/${datasetId}/clusters`,
            title: "Back to Term Clustering",
          }}
          forwardButton={{
            label: "Back to Dataset Overview",
            to: `/datasets/${datasetId}`,
            title: "Go to Dataset Overview",
          }}
          helpContent={
            <>
              <p>Map clustered source terms to standard vocabulary concepts (OMOP CDM).</p>
              <strong>How to use:</strong>
              <ul>
                <li>Select a source term from the Source Terms table to search for matching concepts</li>
                <li>Use filters to narrow results by vocabulary, domain, or concept class</li>
                <li>Click on a target concept to assign it, then click Accept to approve</li>
                <li>Click Auto-Map All Terms to automatically map all unmapped clusters</li>
                <li>Download Mappings to export results when done</li>
              </ul>
            </>
          }
        />

        {/* Stats Section with Actions */}
        <div className={styles["page__stats-section"]}>
          <div className={styles["page__stats-container"]}>
            <StatCard label="Total" value={stats.total} />
            <StatCard label="Mapped" value={`${stats.mapped} (${stats.mappedPercentage}%)`} color="blue" />
            <StatCard label="Approved" value={stats.approved} color="green" />
            <StatCard label="Unmapped" value={stats.unmapped} color="orange" />
          </div>

          <div className={styles["page__toolbar-buttons"]}>
            {isAutoMapping ? (
              <div className={styles["page__auto-map"]}>
                <span className={styles["page__auto-map-label"]}>Auto-mapping in progress</span>
                {autoMapProgress && autoMapProgress.total > 0 && (
                  <span className={styles["page__auto-map-count"]}>
                    {autoMapProgress.completed} / {autoMapProgress.total} clusters
                  </span>
                )}
                <div className={styles["page__auto-map-progress"]}>
                  <ProgressBar
                    progress={
                      autoMapProgress && autoMapProgress.total > 0
                        ? (autoMapProgress.completed / autoMapProgress.total) * 100
                        : 0
                    }
                    showPercentage
                  />
                </div>
                <Button variant="outline" size="small" onClick={handleCancelAutoMap} disabled={isCancellingAutoMap}>
                  {isCancellingAutoMap ? "Cancelling…" : "Cancel"}
                </Button>
              </div>
            ) : (
              <>
                <Button variant="success" onClick={handleAutoMapAll} disabled={isLoading || vocabularies.length === 0}>
                  Auto-Map All Terms
                </Button>

                <Button variant="primary" onClick={handleExport}>
                  Download Mappings
                </Button>
              </>
            )}
          </div>
        </div>

        {error && (
          <div className={styles["page__error"]}>
            {error}
            <Button variant="ghost" size="icon" onClick={() => setError(null)} aria-label="Dismiss error">
              ×
            </Button>
          </div>
        )}

        {/* Main Content */}
        <div className={styles["page__main-layout"]}>
          {/* Source Terms Table */}
          <SourceTermsTable
            mappings={mappings}
            selectedMapping={selectedMapping}
            onSelectMapping={setSelectedMapping}
            onApproveMapping={handleApproveFromTable}
            onDeleteMapping={handleDeleteFromTable}
            isLoading={isLoading}
            isRefreshing={isRefreshing}
            labels={labels}
            selectedLabel={selectedLabel}
            onLabelChange={setSelectedLabel}
          />

          {/* Selection Bar */}
          <div className={styles["selection-bar"]}>
            {selectedMapping ? (
              <>
                <div className={styles["selection-bar__panels"]}>
                  {/* Source Term Panel */}
                  <div className={styles["selection-bar__panel"]}>
                    <span className={styles["selection-bar__panel-label"]}>Source Term</span>
                    <span className={styles["selection-bar__value"]}>{selectedMapping.cluster_title}</span>
                    <div className={styles["selection-bar__meta"]}>
                      <span>Label: {selectedMapping.cluster_label}</span>
                      <span>Freq: {selectedMapping.cluster_total_occurrences}</span>
                      <span>Terms: {selectedMapping.cluster_term_count}</span>
                    </div>
                  </div>

                  <span className={styles["selection-bar__arrow"]}>
                    <FontAwesomeIcon icon={faArrowRightLong} />
                  </span>

                  {/* Target Concept Panel */}
                  <div className={styles["selection-bar__panel"]}>
                    <span className={styles["selection-bar__panel-label"]}>Target Concept</span>
                    {selectedMapping.concept_term_name ? (
                      <>
                        <span className={styles["selection-bar__target"]}>{selectedMapping.concept_term_name}</span>
                        <div className={styles["selection-bar__meta"]}>
                          <span>ID: {selectedMapping.concept_term_id}</span>
                          {selectedMapping.concept_code && <span>Code: {selectedMapping.concept_code}</span>}
                          {selectedMapping.concept_domain && <span>Domain: {selectedMapping.concept_domain}</span>}
                          {selectedMapping.concept_class && <span>Class: {selectedMapping.concept_class}</span>}
                          {selectedMapping.vocabulary_name && <span>Vocab: {selectedMapping.vocabulary_name}</span>}
                        </div>
                      </>
                    ) : (
                      <span className={styles["selection-bar__no-selection"]}>No concept mapped</span>
                    )}
                  </div>
                </div>

                <div className={styles["selection-bar__actions"]}>
                  {selectedMapping.concept_id && (
                    <Button variant="outline" size="small" onClick={handleDeleteMapping}>
                      Remove
                    </Button>
                  )}
                  <Button
                    variant="success"
                    size="small"
                    onClick={() => {
                      if (selectedMapping.concept_id) {
                        handleMapConcept(selectedMapping.concept_id, "approved");
                      }
                    }}
                    disabled={!selectedMapping.concept_id || isMapping}
                  >
                    Accept
                  </Button>
                </div>
              </>
            ) : (
              <div className={styles["selection-bar__info"]}>
                <span className={styles["selection-bar__no-selection"]}>No source term selected</span>
              </div>
            )}
          </div>

          {/* Comment Row */}
          <div className={styles["comment-row"]}>
            <label className={styles["comment-row__label"]} htmlFor="mapping-comment">
              Comment:
            </label>
            <input
              id="mapping-comment"
              type="text"
              className={styles["comment-row__input"]}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Add a comment for the selected mapping"
            />
          </div>

          {/* Bottom Section: Search Filters above Target Concepts */}
          <div className={styles["bottom-section"]}>
            <SearchFiltersPanel
              useSourceTerm={useSourceTerm}
              onUseSourceTermChange={setUseSourceTerm}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              onSearch={handleSearch}
              standardOnly={standardOnly}
              onStandardOnlyChange={setStandardOnly}
              includeSourceTerms={includeSourceTerms}
              onIncludeSourceTermsChange={setIncludeSourceTerms}
              vocabularies={vocabularies}
              selectedVocabularies={selectedVocabularies}
              onSelectedVocabulariesChange={setSelectedVocabularies}
              vocabularyFilterEnabled={vocabularyFilterEnabled}
              onVocabularyFilterEnabledChange={setVocabularyFilterEnabled}
              domainFilter={domainFilter}
              onDomainFilterChange={setDomainFilter}
              domainFilterEnabled={domainFilterEnabled}
              onDomainFilterEnabledChange={setDomainFilterEnabled}
              domains={domains}
              conceptClassFilter={conceptClassFilter}
              onConceptClassFilterChange={setConceptClassFilter}
              conceptClassFilterEnabled={conceptClassFilterEnabled}
              onConceptClassFilterEnabledChange={setConceptClassFilterEnabled}
              conceptClasses={conceptClasses}
            />

            <TargetConceptsList
              selectedMapping={selectedMapping}
              searchResults={searchResults}
              isSearching={isSearching}
              onMapConcept={handleMapConcept}
              pagination={searchPagination}
              currentPage={searchPage}
              onPageChange={handleSearchPageChange}
              sortBy={sortBy}
              sortOrder={sortOrder}
              onSortChange={handleSortChange}
            />
          </div>
        </div>

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
}
