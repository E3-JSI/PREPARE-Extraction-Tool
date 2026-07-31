import { useState, useEffect, useCallback, useMemo } from "react";
import type { Vocabulary, Concept, PaginationMetadata } from "@/types";
import {
  getVocabulary,
  getVocabularyConcepts,
  searchVocabularyConcepts,
  downloadVocabulary as downloadVocabularyAPI,
} from "@/api";

// ================================================
// Types
// ================================================

interface FilterOptions {
  domains: string[];
  conceptClasses: string[];
  standardConcepts: string[];
}

interface Filters {
  searchQuery: string;
  domain: string;
  conceptClass: string;
  standardConcept: string;
}

// ================================================
// Hook
// ================================================

export function useVocabularyConcepts(vocabularyId: number) {
  const [vocabulary, setVocabulary] = useState<Vocabulary | null>(null);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [pagination, setPagination] = useState<PaginationMetadata | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingConcepts, setIsLoadingConcepts] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  // Filters
  const [filters, setFilters] = useState<Filters>({
    searchQuery: "",
    domain: "",
    conceptClass: "",
    standardConcept: "",
  });

  // Debounced search query
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(filters.searchQuery);
    }, 500);
    return () => clearTimeout(timer);
  }, [filters.searchQuery]);

  // Fetch vocabulary metadata
  const fetchVocabulary = useCallback(async () => {
    if (!vocabularyId) return;
    try {
      const response = await getVocabulary(vocabularyId);
      setVocabulary(response.vocabulary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch vocabulary");
    }
  }, [vocabularyId]);

  // Fetch concepts (either paginated list or ES search)
  const fetchConcepts = useCallback(
    async (page = 1, limit = 50, searchQuery?: string, searchFilters?: Omit<Filters, "searchQuery">) => {
      if (!vocabularyId) return;
      setIsLoadingConcepts(true);
      try {
        let response;
        if (searchQuery && searchQuery.trim()) {
          // Use Elasticsearch search
          response = await searchVocabularyConcepts({
            vocabularyId,
            query: searchQuery.trim(),
            page,
            limit,
            domain_id: searchFilters?.domain || undefined,
            concept_class_id: searchFilters?.conceptClass || undefined,
            standard_concept: searchFilters?.standardConcept || undefined,
          });
        } else {
          // Use regular pagination
          response = await getVocabularyConcepts(vocabularyId, page, limit);
        }
        setConcepts(response.concepts);
        setPagination(response.pagination);
        setCurrentPage(page);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch concepts");
      } finally {
        setIsLoadingConcepts(false);
      }
    },
    [vocabularyId]
  );

  // Initial fetch
  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true);
      setError(null);
      await Promise.all([fetchVocabulary(), fetchConcepts(1, 50)]);
      setIsLoading(false);
    };
    loadData();
  }, [fetchVocabulary, fetchConcepts]);

  // Refetch when search query or filters change
  useEffect(() => {
    // Skip initial render (handled by initial fetch)
    if (!vocabulary) return;

    const searchFilters = {
      domain: filters.domain,
      conceptClass: filters.conceptClass,
      standardConcept: filters.standardConcept,
    };
    fetchConcepts(1, 50, debouncedSearchQuery, searchFilters);
    // `vocabulary` is only read as a "loaded yet?" guard — adding it would re-run this
    // (duplicating the initial fetch) when the vocabulary finishes loading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchConcepts, debouncedSearchQuery, filters.domain, filters.conceptClass, filters.standardConcept]);

  // Compute unique filter options from loaded concepts
  const filterOptions = useMemo<FilterOptions>(() => {
    const domains = new Set<string>();
    const conceptClasses = new Set<string>();
    const standardConcepts = new Set<string>();

    concepts.forEach((concept) => {
      if (concept.domain_id) domains.add(concept.domain_id);
      if (concept.concept_class_id) conceptClasses.add(concept.concept_class_id);
      if (concept.standard_concept) standardConcepts.add(concept.standard_concept);
    });

    return {
      domains: Array.from(domains).sort(),
      conceptClasses: Array.from(conceptClasses).sort(),
      standardConcepts: Array.from(standardConcepts).sort(),
    };
  }, [concepts]);

  // Filter concepts client-side (only when not using ES search)
  const filteredConcepts = useMemo(() => {
    // When using ES search, server handles filtering - just apply non-search filters client-side
    if (debouncedSearchQuery) {
      // ES handles search query, but we still filter by domain/class/standard if not passed to ES
      // Since we now pass filters to ES, return concepts as-is
      return concepts;
    }

    // When not searching, apply client-side filters for pagination browsing
    return concepts.filter((concept) => {
      // Domain filter
      if (filters.domain && concept.domain_id !== filters.domain) return false;

      // Concept class filter
      if (filters.conceptClass && concept.concept_class_id !== filters.conceptClass) return false;

      // Standard concept filter
      if (filters.standardConcept && concept.standard_concept !== filters.standardConcept) return false;

      return true;
    });
  }, [concepts, debouncedSearchQuery, filters.domain, filters.conceptClass, filters.standardConcept]);

  // Update filters
  const updateFilter = useCallback((key: keyof Filters, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  // Clear all filters
  const clearFilters = useCallback(() => {
    setFilters({
      searchQuery: "",
      domain: "",
      conceptClass: "",
      standardConcept: "",
    });
  }, []);

  // Download vocabulary
  const downloadVocabulary = useCallback(async () => {
    if (!vocabularyId) return;
    await downloadVocabularyAPI(vocabularyId);
  }, [vocabularyId]);

  // Pagination
  const goToPage = useCallback(
    (page: number) => {
      const searchFilters = {
        domain: filters.domain,
        conceptClass: filters.conceptClass,
        standardConcept: filters.standardConcept,
      };
      fetchConcepts(page, pagination?.limit || 50, debouncedSearchQuery, searchFilters);
    },
    [
      fetchConcepts,
      pagination?.limit,
      debouncedSearchQuery,
      filters.domain,
      filters.conceptClass,
      filters.standardConcept,
    ]
  );

  return {
    vocabulary,
    concepts: filteredConcepts,
    allConcepts: concepts,
    pagination,
    isLoading,
    isLoadingConcepts,
    error,
    currentPage,
    filters,
    filterOptions,
    updateFilter,
    clearFilters,
    downloadVocabulary,
    goToPage,
    fetchConcepts,
  };
}
