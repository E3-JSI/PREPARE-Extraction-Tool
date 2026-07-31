// Pure geometry helpers for LinkArrowOverlay. Kept DOM-free so the anchor-fan
// and lane-assignment math can be unit-tested in isolation.

// Horizontal padding kept clear of each span edge when fanning anchors.
export const ANCHOR_INSET = 4;
// Spans narrower than this keep a single centered anchor (no fan) — too little
// room to spread multiple attachment points apart legibly.
export const NARROW_SPAN_THRESHOLD = 24;
// Offset of the first (lane 0) horizontal run from the line edge it hugs.
// Matches the original fixed ±4px behaviour.
export const BASE_GAP = 4;
// Additional offset per lane; a touch more than the 1.5 stroke so parallel
// lanes read as separate lines.
export const LANE_SPACING = 5;
// Keep lanes from crowding the far line edge when compressing to fit a gap.
export const LANE_MARGIN = 2;

export interface FanAttachment {
  // Unique id for this endpoint (e.g. `${linkId}:from`).
  key: string;
  // Anchor X of the link's *other* endpoint — used to order the fan so arrows
  // leave the span left-to-right in a low-crossing order.
  otherX: number;
}

/**
 * Spread the attachment X positions of the links touching a single term span
 * across the span's usable width. With one attachment, or a span narrower than
 * `narrowThreshold`, every attachment keeps the span center.
 *
 * Returns a map of attachment key → anchor X (container-relative).
 */
export function assignAnchorFan(
  rectLeft: number,
  rectWidth: number,
  attachments: FanAttachment[],
  inset: number = ANCHOR_INSET,
  narrowThreshold: number = NARROW_SPAN_THRESHOLD
): Map<string, number> {
  const result = new Map<string, number>();
  const center = rectLeft + rectWidth / 2;

  if (attachments.length <= 1 || rectWidth < narrowThreshold) {
    for (const a of attachments) result.set(a.key, center);
    return result;
  }

  const sorted = [...attachments].sort((a, b) => a.otherX - b.otherX);
  const usableWidth = rectWidth - 2 * inset;
  const n = sorted.length;
  sorted.forEach((a, i) => {
    const t = (i + 0.5) / n;
    result.set(a.key, rectLeft + inset + t * usableWidth);
  });
  return result;
}

export interface LaneRun {
  // Unique id for this arrow's horizontal run (the link id).
  key: string;
  // Groups runs that share an inter-line gap and hug the same edge.
  groupKey: string;
  // Horizontal extent start — runs are laned left-to-right by this.
  minX: number;
  // The container-relative Y of the line edge this run hugs.
  edgeY: number;
  // +1 places the run below the edge, -1 above it.
  sign: 1 | -1;
  // Inter-line gap available for stacking lanes without hitting the next line.
  availableGap: number;
}

/**
 * Assign a parallel lane to each horizontal run so arrows crossing the same gap
 * stack instead of overlapping. Lanes are ordered left-to-right by `minX`. Lane
 * spacing compresses when `BASE_GAP + n*LANE_SPACING` would overflow the gap.
 *
 * Returns a map of run key → horizontal-segment Y (container-relative).
 */
export function assignLanes(
  runs: LaneRun[],
  baseGap: number = BASE_GAP,
  laneSpacing: number = LANE_SPACING,
  margin: number = LANE_MARGIN
): Map<string, number> {
  const result = new Map<string, number>();
  const groups = new Map<string, LaneRun[]>();
  for (const r of runs) {
    const g = groups.get(r.groupKey);
    if (g) g.push(r);
    else groups.set(r.groupKey, [r]);
  }

  for (const group of groups.values()) {
    const sorted = [...group].sort((a, b) => a.minX - b.minX);
    const maxLaneIndex = sorted.length - 1;
    // Use the tightest gap in the group so no lane overflows any member's line.
    const availableGap = Math.min(...sorted.map((r) => r.availableGap));
    const availableForLanes = availableGap - margin;

    let spacing = laneSpacing;
    if (maxLaneIndex > 0) {
      const desiredMax = baseGap + maxLaneIndex * laneSpacing;
      if (desiredMax > availableForLanes) {
        spacing = Math.max(0, (availableForLanes - baseGap) / maxLaneIndex);
      }
    }

    sorted.forEach((r, i) => {
      let offset = baseGap + i * spacing;
      if (availableForLanes > 0 && offset > availableForLanes) offset = availableForLanes;
      result.set(r.key, r.edgeY + r.sign * offset);
    });
  }

  return result;
}
