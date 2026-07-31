import React, { useMemo } from "react";

import Table, { type Column, type SortState } from "@components/Table";
import Pagination from "@components/Pagination";

import type { ClusterMapping, ConceptSearchResult, PaginationMetadata } from "@/types";

import styles from "./styles.module.css";

interface TargetConceptsListProps {
  selectedMapping: ClusterMapping | null;
  searchResults: ConceptSearchResult[];
  isSearching: boolean;
  onMapConcept: (conceptId: number) => void;
  pagination: PaginationMetadata | null;
  currentPage: number;
  onPageChange: (page: number) => void;
  sortBy: "relevance" | "name" | "domain";
  sortOrder: "asc" | "desc";
  onSortChange: (field: "relevance" | "name" | "domain") => void;
}

const SORT_KEY_MAP: Record<string, "relevance" | "name" | "domain"> = {
  score: "relevance",
  vocab_term_name: "name",
  domain_id: "domain",
};

const REVERSE_SORT_MAP: Record<string, string> = {
  relevance: "score",
  name: "vocab_term_name",
  domain: "domain_id",
};

const TargetConceptsList: React.FC<TargetConceptsListProps> = ({
  selectedMapping,
  searchResults,
  isSearching,
  onMapConcept,
  pagination,
  currentPage,
  onPageChange,
  sortBy,
  sortOrder,
  onSortChange,
}) => {
  const columns: Column<ConceptSearchResult>[] = useMemo(
    () => [
      {
        key: "score",
        header: "Score",
        sortable: true,
        render: (result: ConceptSearchResult) => result.score.toFixed(2),
      },
      {
        key: "concept_id",
        header: "Concept ID",
        render: (result: ConceptSearchResult) => result.concept.vocab_term_id,
      },
      {
        key: "vocab_term_name",
        header: "Concept Name",
        sortable: true,
        render: (result: ConceptSearchResult) => result.concept.vocab_term_name,
      },
      {
        key: "domain_id",
        header: "Domain",
        sortable: true,
        render: (result: ConceptSearchResult) => result.concept.domain_id,
      },
      {
        key: "concept_class_id",
        header: "Concept Class",
        render: (result: ConceptSearchResult) => result.concept.concept_class_id,
      },
      {
        key: "vocabulary_name",
        header: "Vocabulary",
        render: (result: ConceptSearchResult) => result.vocabulary_name,
      },
      {
        key: "concept_code",
        header: "Concept Code",
        render: (result: ConceptSearchResult) => result.concept.concept_code,
      },
      {
        key: "standard_concept",
        header: "Standard",
        render: (result: ConceptSearchResult) =>
          result.concept.standard_concept === "S" ? "S" : result.concept.standard_concept === "C" ? "C" : "—",
      },
    ],
    []
  );

  const sort: SortState = {
    key: REVERSE_SORT_MAP[sortBy] || sortBy,
    direction: sortOrder,
  };

  const handleSortChange = (key: string) => {
    const mappedField = SORT_KEY_MAP[key];
    if (mappedField) {
      onSortChange(mappedField);
    }
  };

  const emptyMessage =
    !selectedMapping && searchResults.length === 0
      ? "Select a source term to search for concepts"
      : "No matching concepts found";

  return (
    <div className={styles["target-concepts-list-panel"]}>
      <div className={styles["target-concepts-list-panel__header"]}>
        <h3 className={styles["target-concepts-list-panel__title"]}>Target Concepts</h3>
        {pagination && (
          <span className={styles["target-concepts-list-panel__total-results"]}>{pagination.total} results</span>
        )}
      </div>
      <div className={styles["target-concepts-list-panel__content"]}>
        <Table
          columns={columns}
          data={searchResults}
          keyExtractor={(result, idx) => `${result.concept.id}-${idx}`}
          onRowClick={(result) => onMapConcept(result.concept.id)}
          isRowSelected={(result) => selectedMapping?.concept_id === result.concept.id}
          isLoadingOverlay={isSearching}
          sort={sort}
          onSortChange={handleSortChange}
          stickyHeader
          ariaLabel="Target concepts"
          emptyMessage={emptyMessage}
        />
        {pagination && pagination.total_pages > 1 && (
          <div className={styles["target-concepts-list-panel__pagination-wrapper"]}>
            <Pagination currentPage={currentPage} totalPages={pagination.total_pages} onPageChange={onPageChange} />
          </div>
        )}
      </div>
    </div>
  );
};

export default TargetConceptsList;
