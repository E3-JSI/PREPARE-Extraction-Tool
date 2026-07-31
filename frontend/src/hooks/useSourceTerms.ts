import { useCallback } from "react";
import type { SourceTerm, SourceTermCreate, SourceTermUpdate } from "@/types";
import {
  createSourceTerm as createSourceTermAPI,
  deleteSourceTerm as deleteSourceTermAPI,
  updateSourceTerm as updateSourceTermAPI,
} from "@/api";
import {
  createSourceTermLink as createSourceTermLinkAPI,
  deleteSourceTermLink as deleteSourceTermLinkAPI,
  getRecordSourceTerms,
} from "@/api/sourceTerms";

interface UseSourceTermsParams {
  datasetId: number;
  selectedRecordId: number | null;
  setSelectedRecordTerms: React.Dispatch<React.SetStateAction<SourceTerm[]>>;
  fetchStats: () => Promise<void>;
}

export function useSourceTerms({
  datasetId,
  selectedRecordId,
  setSelectedRecordTerms,
  fetchStats,
}: UseSourceTermsParams) {
  const addSourceTerm = useCallback(
    async (term: SourceTermCreate) => {
      if (!selectedRecordId) {
        throw new Error("No record selected");
      }
      const response = await createSourceTermAPI(datasetId, selectedRecordId, term);
      // After creating, re-fetch all source terms to get backend-calculated fields (like linked dates)
      const refreshed = await getRecordSourceTerms(datasetId, selectedRecordId, 500);
      setSelectedRecordTerms(refreshed.source_terms);
      await fetchStats();
      // Optionally, return the new term (find by value/label)
      return (
        refreshed.source_terms.find(
          (t) => t.value === response.source_term.value && t.label === response.source_term.label
        ) ?? response.source_term
      );
    },
    [datasetId, selectedRecordId, setSelectedRecordTerms, fetchStats]
  );

  const removeSourceTerm = useCallback(
    async (termId: number) => {
      await deleteSourceTermAPI(termId);
      // After deleting, re-fetch all source terms to get backend-calculated fields (like linked dates)
      if (selectedRecordId) {
        const refreshed = await getRecordSourceTerms(datasetId, selectedRecordId, 500);
        setSelectedRecordTerms(refreshed.source_terms);
      } else {
        setSelectedRecordTerms((prev) => prev.filter((t) => t.id !== termId));
      }
      await fetchStats();
    },
    [datasetId, selectedRecordId, setSelectedRecordTerms, fetchStats]
  );

  const updateSourceTermLabel = useCallback(
    async (termId: number, newLabel: string) => {
      const response = await updateSourceTermAPI(termId, { label: newLabel });
      // Preserve existing links since the PATCH response doesn't include them
      setSelectedRecordTerms((prev) =>
        prev.map((t) => (t.id === termId ? { ...response.source_term, links: t.links } : t))
      );
      return response.source_term;
    },
    [setSelectedRecordTerms]
  );

  const updateSourceTermDate = useCallback(
    async (termId: number, newDate: string | null) => {
      // Send null to clear date, or YYYY-MM-DD string to set
      const payload: SourceTermUpdate = { linked_visit_date: newDate };
      const response = await updateSourceTermAPI(termId, payload);
      // Preserve existing links since the PATCH response doesn't include them
      setSelectedRecordTerms((prev) =>
        prev.map((t) => (t.id === termId ? { ...response.source_term, links: t.links } : t))
      );
      return response.source_term;
    },
    [setSelectedRecordTerms]
  );

  const addLink = useCallback(
    async (fromTermId: number, toTermId: number) => {
      await createSourceTermLinkAPI(fromTermId, toTermId);
      if (selectedRecordId) {
        const refreshed = await getRecordSourceTerms(datasetId, selectedRecordId, 500);
        setSelectedRecordTerms(refreshed.source_terms);
      }
    },
    [datasetId, selectedRecordId, setSelectedRecordTerms]
  );

  const removeLink = useCallback(
    async (linkId: number) => {
      await deleteSourceTermLinkAPI(linkId);
      if (selectedRecordId) {
        const refreshed = await getRecordSourceTerms(datasetId, selectedRecordId, 500);
        setSelectedRecordTerms(refreshed.source_terms);
      }
    },
    [datasetId, selectedRecordId, setSelectedRecordTerms]
  );

  return {
    addSourceTerm,
    removeSourceTerm,
    updateSourceTermLabel,
    updateSourceTermDate,
    addLink,
    removeLink,
  };
}
