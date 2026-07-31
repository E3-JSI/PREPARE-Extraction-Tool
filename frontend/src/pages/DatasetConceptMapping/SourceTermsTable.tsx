import React, { useState, useMemo, useEffect } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck, faXmark, faMagnifyingGlass, faQuestion } from "@fortawesome/free-solid-svg-icons";
import classNames from "classnames";

import Table, { type Column } from "@components/Table";
import LoadingSpinner from "@components/LoadingSpinner";
import { Select } from "@components/Select";
import Pagination from "@components/Pagination";

import type { ClusterMapping } from "@/types";
import type { IconProp } from "@fortawesome/fontawesome-svg-core";

import styles from "./styles.module.css";

function getStatusIcon(status: string): IconProp {
  const statusMap: Record<string, IconProp> = {
    unmapped: faQuestion,
    pending: faMagnifyingGlass,
    approved: faCheck,
    rejected: faXmark,
  };
  return statusMap[status] || faQuestion;
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

interface SourceTermsTableProps {
  mappings: ClusterMapping[];
  selectedMapping: ClusterMapping | null;
  onSelectMapping: (mapping: ClusterMapping) => void;
  onApproveMapping: (mapping: ClusterMapping) => void;
  onDeleteMapping: (mapping: ClusterMapping) => void;
  isLoading: boolean;
  isRefreshing?: boolean;
  labels: string[];
  selectedLabel: string;
  onLabelChange: (label: string) => void;
}

const SourceTermsTable: React.FC<SourceTermsTableProps> = ({
  mappings,
  selectedMapping,
  onSelectMapping,
  onApproveMapping,
  onDeleteMapping,
  isLoading,
  isRefreshing = false,
  labels,
  selectedLabel,
  onLabelChange,
}) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Reset pagination when the mappings content or label changes. Keying on the
  // `mappings` reference (not just its length) ensures we reset even when a
  // refetch returns a same-count list, so currentPage can't point past data.
  useEffect(() => {
    setCurrentPage(1);
    setSearchQuery("");
  }, [mappings, selectedLabel]);

  // Filter mappings by search query
  const filteredMappings = useMemo(() => {
    if (!searchQuery.trim()) return mappings;

    const query = searchQuery.toLowerCase();
    return mappings.filter(
      (m) =>
        m.cluster_title.toLowerCase().includes(query) ||
        m.cluster_id.toString().includes(query) ||
        (m.concept_term_name && m.concept_term_name.toLowerCase().includes(query)) ||
        (m.concept_term_id && m.concept_term_id.toLowerCase().includes(query))
    );
  }, [mappings, searchQuery]);

  // Calculate pagination
  const totalPages = Math.ceil(filteredMappings.length / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = startIndex + pageSize;
  const paginatedMappings = filteredMappings.slice(startIndex, endIndex);

  // Reset to page 1 when search or page size changes
  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    setCurrentPage(1);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setCurrentPage(1);
  };

  const goToPage = (page: number) => {
    setCurrentPage(Math.max(1, Math.min(page, totalPages)));
  };

  const columns: Column<ClusterMapping>[] = useMemo(
    () => [
      {
        key: "status",
        header: "Status",
        align: "center",
        render: (mapping: ClusterMapping) => <FontAwesomeIcon icon={getStatusIcon(mapping.status)} />,
      },
      {
        key: "cluster_title",
        header: "Source Term",
      },
      {
        key: "cluster_total_occurrences",
        header: "Freq",
      },
      {
        key: "cluster_label",
        header: "Label",
        render: (mapping: ClusterMapping) => (
          <span
            className={classNames(styles["label-badge"], styles[`label-badge--${mapping.cluster_label.toLowerCase()}`])}
          >
            {mapping.cluster_label}
          </span>
        ),
      },
      {
        key: "concept_term_id",
        header: "Concept ID",
        render: (mapping: ClusterMapping) => mapping.concept_term_id || "—",
      },
      {
        key: "concept_term_name",
        header: "Concept Name",
        render: (mapping: ClusterMapping) => mapping.concept_term_name || "—",
      },
      {
        key: "concept_domain",
        header: "Domain",
        render: (mapping: ClusterMapping) => mapping.concept_domain || "—",
      },
      {
        key: "vocabulary_name",
        header: "Vocabulary",
        render: (mapping: ClusterMapping) => mapping.vocabulary_name || "—",
      },
      {
        key: "actions",
        header: "Actions",
        render: (mapping: ClusterMapping) => (
          <div className={styles["source-terms-section__actions-cell"]}>
            <button
              className={classNames(
                styles["source-terms-section__action-btn"],
                styles["source-terms-section__action-btn--approve"]
              )}
              onClick={(e) => {
                e.stopPropagation();
                onApproveMapping(mapping);
              }}
              disabled={!mapping.concept_id || mapping.status === "approved"}
            >
              Accept
            </button>
            <button
              className={classNames(
                styles["source-terms-section__action-btn"],
                styles["source-terms-section__action-btn--remove"]
              )}
              onClick={(e) => {
                e.stopPropagation();
                onDeleteMapping(mapping);
              }}
              disabled={!mapping.concept_id}
            >
              Remove
            </button>
          </div>
        ),
      },
    ],
    [onApproveMapping, onDeleteMapping]
  );

  return (
    <div className={styles["source-terms-section"]}>
      {/* Search and Controls Header */}
      <div className={styles["source-terms-section__header"]}>
        <div className={styles["source-terms-section__header-left"]}>
          <Select
            options={labels.map((l) => ({ value: l, label: l }))}
            value={selectedLabel}
            onValueChange={onLabelChange}
            placeholder="All Categories"
            aria-label="Filter by category"
            fullWidth={false}
            className={styles["source-terms-section__label-select"]}
          />
          <div className={styles["source-terms-section__search"]}>
            <input
              type="text"
              placeholder="Search source terms..."
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              className={styles["source-terms-section__search-input"]}
              aria-label="Search source terms"
            />
            {searchQuery && (
              <button
                className={styles["source-terms-section__clear-btn"]}
                onClick={() => handleSearchChange("")}
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </div>
        </div>
        <div className={styles["source-terms-section__info"]}>
          Showing {filteredMappings.length === 0 ? 0 : startIndex + 1}–{Math.min(endIndex, filteredMappings.length)} of{" "}
          {filteredMappings.length}
          {searchQuery && ` (filtered from ${mappings.length})`}
        </div>
      </div>

      {/* Table */}
      <div className={styles["source-terms-section__table-wrapper"]}>
        <Table
          columns={columns}
          data={paginatedMappings}
          keyExtractor={(mapping) => mapping.cluster_id}
          onRowClick={onSelectMapping}
          isRowSelected={(mapping) => selectedMapping?.cluster_id === mapping.cluster_id}
          isLoading={isLoading}
          isLoadingOverlay={isRefreshing}
          loadingContent={<LoadingSpinner size="small" text="Loading source terms..." />}
          stickyHeader
          ariaLabel="Source terms"
          emptyMessage={searchQuery ? "No matching source terms found" : "No source terms found"}
        />
      </div>

      {/* Pagination Controls */}
      {!isLoading && filteredMappings.length > 0 && (
        <div className={styles["source-terms-section__pagination-bar"]}>
          <div className={styles["source-terms-section__page-size-selector"]}>
            <label htmlFor="page-size">Rows per page:</label>
            <Select
              id="page-size"
              options={PAGE_SIZE_OPTIONS.map((s) => ({ value: String(s), label: String(s) }))}
              value={String(pageSize)}
              onValueChange={(v) => handlePageSizeChange(Number(v))}
              size="small"
              fullWidth={false}
              className={styles["source-terms-section__page-size-select"]}
            />
          </div>

          <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={goToPage} />
        </div>
      )}
    </div>
  );
};

export default SourceTermsTable;
