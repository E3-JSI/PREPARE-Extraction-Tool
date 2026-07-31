import { describe, it, expect } from "vitest";

import {
  assignAnchorFan,
  assignLanes,
  ANCHOR_INSET,
  NARROW_SPAN_THRESHOLD,
  BASE_GAP,
  LANE_SPACING,
  LANE_MARGIN,
  type FanAttachment,
  type LaneRun,
} from "../linkArrowGeometry";

describe("assignAnchorFan", () => {
  it("fans a term with 3 links into 3 distinct X positions ordered by the other endpoint", () => {
    const rectLeft = 100;
    const rectWidth = 60; // >= NARROW_SPAN_THRESHOLD
    // Deliberately unordered — highest otherX first — to prove ordering works.
    const attachments: FanAttachment[] = [
      { key: "c", otherX: 500 },
      { key: "a", otherX: 100 },
      { key: "b", otherX: 300 },
    ];

    const fan = assignAnchorFan(rectLeft, rectWidth, attachments);

    const xa = fan.get("a")!;
    const xb = fan.get("b")!;
    const xc = fan.get("c")!;

    // Three distinct positions.
    expect(new Set([xa, xb, xc]).size).toBe(3);
    // Ordered left-to-right by the other endpoint's X.
    expect(xa).toBeLessThan(xb);
    expect(xb).toBeLessThan(xc);
    // All within the usable (inset) width of the span.
    for (const x of [xa, xb, xc]) {
      expect(x).toBeGreaterThanOrEqual(rectLeft + ANCHOR_INSET);
      expect(x).toBeLessThanOrEqual(rectLeft + rectWidth - ANCHOR_INSET);
    }
    // Evenly distributed: t = (i + 0.5) / n across usable width.
    const usable = rectWidth - 2 * ANCHOR_INSET;
    expect(xa).toBeCloseTo(rectLeft + ANCHOR_INSET + (0.5 / 3) * usable);
    expect(xb).toBeCloseTo(rectLeft + ANCHOR_INSET + (1.5 / 3) * usable);
    expect(xc).toBeCloseTo(rectLeft + ANCHOR_INSET + (2.5 / 3) * usable);
  });

  it("keeps a single-link term centered", () => {
    const rectLeft = 100;
    const rectWidth = 60;
    const fan = assignAnchorFan(rectLeft, rectWidth, [{ key: "solo", otherX: 400 }]);
    expect(fan.get("solo")).toBe(rectLeft + rectWidth / 2);
  });

  it("keeps a narrow multi-link span centered (no cramming)", () => {
    const rectLeft = 100;
    const rectWidth = NARROW_SPAN_THRESHOLD - 1;
    const attachments: FanAttachment[] = [
      { key: "a", otherX: 100 },
      { key: "b", otherX: 300 },
    ];
    const fan = assignAnchorFan(rectLeft, rectWidth, attachments);
    const center = rectLeft + rectWidth / 2;
    expect(fan.get("a")).toBe(center);
    expect(fan.get("b")).toBe(center);
  });
});

describe("assignLanes", () => {
  it("assigns lanes 0,1,2 with increasing distance from the edge for 3 runs in one gap", () => {
    const edgeY = 200;
    const runs: LaneRun[] = [
      { key: "mid", groupKey: "g", minX: 200, edgeY, sign: 1, availableGap: 40 },
      { key: "left", groupKey: "g", minX: 100, edgeY, sign: 1, availableGap: 40 },
      { key: "right", groupKey: "g", minX: 300, edgeY, sign: 1, availableGap: 40 },
    ];

    const lanes = assignLanes(runs);

    const yLeft = lanes.get("left")!;
    const yMid = lanes.get("mid")!;
    const yRight = lanes.get("right")!;

    // Lane order follows minX; lane 0 sits at BASE_GAP, each next +LANE_SPACING.
    expect(yLeft).toBeCloseTo(edgeY + BASE_GAP);
    expect(yMid).toBeCloseTo(edgeY + BASE_GAP + LANE_SPACING);
    expect(yRight).toBeCloseTo(edgeY + BASE_GAP + 2 * LANE_SPACING);

    // |horizY - edge| strictly increases with lane index.
    expect(Math.abs(yLeft - edgeY)).toBeLessThan(Math.abs(yMid - edgeY));
    expect(Math.abs(yMid - edgeY)).toBeLessThan(Math.abs(yRight - edgeY));
  });

  it("respects the sign (backward/same-line runs stack above the edge)", () => {
    const edgeY = 200;
    const runs: LaneRun[] = [
      { key: "a", groupKey: "g", minX: 100, edgeY, sign: -1, availableGap: 40 },
      { key: "b", groupKey: "g", minX: 200, edgeY, sign: -1, availableGap: 40 },
    ];
    const lanes = assignLanes(runs);
    expect(lanes.get("a")).toBeCloseTo(edgeY - BASE_GAP);
    expect(lanes.get("b")).toBeCloseTo(edgeY - BASE_GAP - LANE_SPACING);
  });

  it("keeps separate gap groups independent", () => {
    const runs: LaneRun[] = [
      { key: "g1a", groupKey: "g1", minX: 100, edgeY: 100, sign: 1, availableGap: 40 },
      { key: "g1b", groupKey: "g1", minX: 200, edgeY: 100, sign: 1, availableGap: 40 },
      { key: "g2a", groupKey: "g2", minX: 100, edgeY: 300, sign: 1, availableGap: 40 },
    ];
    const lanes = assignLanes(runs);
    // Each group restarts at lane 0.
    expect(lanes.get("g1a")).toBeCloseTo(100 + BASE_GAP);
    expect(lanes.get("g2a")).toBeCloseTo(300 + BASE_GAP);
  });

  it("compresses lane spacing when the gap is too small to fit BASE_GAP + n*LANE_SPACING", () => {
    const edgeY = 200;
    // Gap of 12 (minus margin) cannot fit BASE_GAP + 2*LANE_SPACING = 14.
    const availableGap = 12;
    const runs: LaneRun[] = [
      { key: "a", groupKey: "g", minX: 100, edgeY, sign: 1, availableGap },
      { key: "b", groupKey: "g", minX: 200, edgeY, sign: 1, availableGap },
      { key: "c", groupKey: "g", minX: 300, edgeY, sign: 1, availableGap },
    ];

    const lanes = assignLanes(runs);
    const ya = lanes.get("a")!;
    const yb = lanes.get("b")!;
    const yc = lanes.get("c")!;

    const offA = ya - edgeY;
    const offB = yb - edgeY;
    const offC = yc - edgeY;

    // Still ordered and distinct.
    expect(offA).toBeLessThan(offB);
    expect(offB).toBeLessThan(offC);
    // Compressed: spacing tighter than the nominal LANE_SPACING.
    expect(offB - offA).toBeLessThan(LANE_SPACING);
    // Lane 0 keeps BASE_GAP; furthest lane fits within the gap (minus margin).
    expect(offA).toBeCloseTo(BASE_GAP);
    expect(offC).toBeLessThanOrEqual(availableGap - LANE_MARGIN);
  });
});
