/**
 * Human-readable summary for a completed "cluster all labels" job, e.g.
 * "Clustered 4 labels, skipped 2 (reviewed)". Skipped labels are those that
 * already had a reviewed cluster and were left untouched.
 */
export function formatClusterAllSummary(clusteredLabels: string[], skippedLabels: string[]): string {
  const clustered = clusteredLabels.length;
  const skipped = skippedLabels.length;

  const clusteredPart = `Clustered ${clustered} label${clustered === 1 ? "" : "s"}`;
  if (skipped === 0) {
    return clusteredPart;
  }
  return `${clusteredPart}, skipped ${skipped} (reviewed)`;
}
