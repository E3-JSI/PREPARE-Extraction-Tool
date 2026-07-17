import { describe, it, expect } from "vitest";
import { formatClusterAllSummary } from "../clusterSummary";

describe("formatClusterAllSummary", () => {
  it("reports clustered and skipped labels", () => {
    expect(formatClusterAllSummary(["A", "B", "C", "D"], ["E", "F"])).toBe("Clustered 4 labels, skipped 2 (reviewed)");
  });

  it("omits the skipped clause when nothing was skipped", () => {
    expect(formatClusterAllSummary(["A", "B", "C"], [])).toBe("Clustered 3 labels");
  });

  it("uses the singular form for a single clustered label", () => {
    expect(formatClusterAllSummary(["A"], [])).toBe("Clustered 1 label");
  });

  it("handles the all-skipped case", () => {
    expect(formatClusterAllSummary([], ["A", "B"])).toBe("Clustered 0 labels, skipped 2 (reviewed)");
  });
});
