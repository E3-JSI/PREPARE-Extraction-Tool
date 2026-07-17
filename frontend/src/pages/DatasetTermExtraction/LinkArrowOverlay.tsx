import React, { useEffect, useMemo, useState } from "react";

import type { SourceTerm, SourceTermLink } from "@/types";

import { assignAnchorFan, assignLanes, type FanAttachment, type LaneRun } from "./linkArrowGeometry";
import styles from "./styles.module.css";

const ARC_COLOR = "#64748b";
const MARKER_ID = "link-arrowhead";

// If the tops of two spans differ by more than this, treat them as on different lines
const SAME_LINE_THRESHOLD = 15;

interface ArcCoords {
  link: SourceTermLink;
  d: string;
}

interface LinkArrowOverlayProps {
  containerRef: React.RefObject<HTMLElement | null>;
  annotations: SourceTerm[];
  hoveredTermId: number | null;
  onHoverChange: (id: number | null) => void;
  interactive?: boolean;
}

function deduplicateLinks(annotations: SourceTerm[]): SourceTermLink[] {
  const seen = new Set<number>();
  const result: SourceTermLink[] = [];
  for (const term of annotations) {
    for (const link of term.links ?? []) {
      if (!seen.has(link.id)) {
        seen.add(link.id);
        result.push(link);
      }
    }
  }
  return result;
}

const LinkArrowOverlay: React.FC<LinkArrowOverlayProps> = ({
  containerRef,
  annotations,
  hoveredTermId,
  onHoverChange,
  interactive = true,
}) => {
  const [arcs, setArcs] = useState<ArcCoords[]>([]);
  const [tick, setTick] = useState(0);

  const uniqueLinks = useMemo(() => deduplicateLinks(annotations), [annotations]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => setTick((t) => t + 1));
    ro.observe(container);
    return () => ro.disconnect();
  }, [containerRef]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !uniqueLinks.length) {
      setArcs([]);
      return;
    }

    const containerRect = container.getBoundingClientRect();

    // Pass 1 — resolve each link's DOM geometry into a plain descriptor. The
    // endpoint that touches each term span is recorded as a fan attachment
    // (grouped per span line box), and the horizontal run as a lane run. The
    // actual anchor X / horizontal Y come from the pure helpers below.
    interface Endpoint {
      termId: number;
      // The chosen line box (first/last) for this endpoint.
      rectLeft: number;
      rectWidth: number;
      rectTop: number;
      // The container-relative Y where the vertical stub meets the span.
      stubY: number;
      // Base (un-fanned) center X of the *other* endpoint, for fan ordering.
      otherCenterX: number;
    }
    interface Descriptor {
      link: SourceTermLink;
      from: Endpoint;
      to: Endpoint;
      edgeY: number;
      sign: 1 | -1;
      availableGap: number;
    }

    const descriptors: Descriptor[] = [];
    const fanGroups = new Map<string, { rectLeft: number; rectWidth: number; attachments: FanAttachment[] }>();

    const registerAttachment = (termId: number, ep: Endpoint, key: string) => {
      const groupKey = `${termId}:${Math.round(ep.rectTop)}`;
      let group = fanGroups.get(groupKey);
      if (!group) {
        group = { rectLeft: ep.rectLeft, rectWidth: ep.rectWidth, attachments: [] };
        fanGroups.set(groupKey, group);
      }
      group.attachments.push({ key, otherX: ep.otherCenterX });
    };

    for (const link of uniqueLinks) {
      const fromEl = container.querySelector<HTMLElement>(`[data-term-id="${link.from_term_id}"]`);
      const toEl = container.querySelector<HTMLElement>(`[data-term-id="${link.to_term_id}"]`);
      if (!fromEl || !toEl) continue;

      // getClientRects() returns one rect per visual line box — correct for
      // wrapped spans where getBoundingClientRect() gives a misleading union box
      const fromRects = Array.from(fromEl.getClientRects());
      const toRects = Array.from(toEl.getClientRects());
      if (!fromRects.length || !toRects.length) continue;

      const fromFirst = fromRects[0];
      const fromLast = fromRects[fromRects.length - 1];
      const toFirst = toRects[0];
      const toLast = toRects[toRects.length - 1];

      const y1Top = fromFirst.top - containerRect.top;
      const y1Bot = fromLast.bottom - containerRect.top;
      const y2Top = toFirst.top - containerRect.top;
      const y2Bot = toLast.bottom - containerRect.top;

      // X centers use the relevant line box, not the union bounding box
      const x1First = fromFirst.left + fromFirst.width / 2 - containerRect.left;
      const x1Last = fromLast.left + fromLast.width / 2 - containerRect.left;
      const x2First = toFirst.left + toFirst.width / 2 - containerRect.left;
      const x2Last = toLast.left + toLast.width / 2 - containerRect.left;

      const relLeft = (r: DOMRect) => r.left - containerRect.left;
      const relTop = (r: DOMRect) => r.top - containerRect.top;

      const sameLine = Math.abs(y1Top - y2Top) < SAME_LINE_THRESHOLD;

      let from: Endpoint;
      let to: Endpoint;
      let edgeY: number;
      let sign: 1 | -1;
      let availableGap: number;

      if (sameLine) {
        // Horizontal sits above the spans — in the inter-line gap above the line
        from = {
          termId: link.from_term_id,
          rectLeft: relLeft(fromFirst),
          rectWidth: fromFirst.width,
          rectTop: relTop(fromFirst),
          stubY: y1Top,
          otherCenterX: x2First,
        };
        to = {
          termId: link.to_term_id,
          rectLeft: relLeft(toFirst),
          rectWidth: toFirst.width,
          rectTop: relTop(toFirst),
          stubY: y2Top,
          otherCenterX: x1First,
        };
        edgeY = Math.min(y1Top, y2Top);
        sign = -1;
        // No previous-line Y on hand; the line's own height is a safe gap proxy.
        availableGap = Math.max(0, y1Bot - y1Top);
      } else if (y1Top < y2Top) {
        // Forward: horizontal sits below the from-span — in the inter-line gap
        from = {
          termId: link.from_term_id,
          rectLeft: relLeft(fromLast),
          rectWidth: fromLast.width,
          rectTop: relTop(fromLast),
          stubY: y1Bot,
          otherCenterX: x2First,
        };
        to = {
          termId: link.to_term_id,
          rectLeft: relLeft(toFirst),
          rectWidth: toFirst.width,
          rectTop: relTop(toFirst),
          stubY: y2Top,
          otherCenterX: x1Last,
        };
        edgeY = y1Bot;
        sign = 1;
        availableGap = Math.max(0, y2Top - y1Bot);
      } else {
        // Backward: horizontal sits above the from-span — in the inter-line gap
        from = {
          termId: link.from_term_id,
          rectLeft: relLeft(fromFirst),
          rectWidth: fromFirst.width,
          rectTop: relTop(fromFirst),
          stubY: y1Top,
          otherCenterX: x2Last,
        };
        to = {
          termId: link.to_term_id,
          rectLeft: relLeft(toLast),
          rectWidth: toLast.width,
          rectTop: relTop(toLast),
          stubY: y2Bot,
          otherCenterX: x1First,
        };
        edgeY = y1Top;
        sign = -1;
        availableGap = Math.max(0, y1Top - y2Bot);
      }

      registerAttachment(link.from_term_id, from, `${link.id}:from`);
      registerAttachment(link.to_term_id, to, `${link.id}:to`);
      descriptors.push({ link, from, to, edgeY, sign, availableGap });
    }

    // Pass 2 — fan shared-term anchors across each span's usable width.
    const anchorX = new Map<string, number>();
    for (const group of fanGroups.values()) {
      const fan = assignAnchorFan(group.rectLeft, group.rectWidth, group.attachments);
      for (const [key, x] of fan) anchorX.set(key, x);
    }

    // Pass 3 — assign a per-gap lane to each horizontal run so parallel arrows
    // stack instead of overlapping. Group by rounded edge Y + direction sign.
    const laneRuns: LaneRun[] = descriptors.map((desc) => {
      const fromX = anchorX.get(`${desc.link.id}:from`) ?? desc.from.rectLeft + desc.from.rectWidth / 2;
      const toX = anchorX.get(`${desc.link.id}:to`) ?? desc.to.rectLeft + desc.to.rectWidth / 2;
      return {
        key: String(desc.link.id),
        groupKey: `${Math.round(desc.edgeY)}:${desc.sign}`,
        minX: Math.min(fromX, toX),
        edgeY: desc.edgeY,
        sign: desc.sign,
        availableGap: desc.availableGap,
      };
    });
    const horizYByLink = assignLanes(laneRuns);

    // Pass 4 — emit the orthogonal (stepped) path per link.
    const computed: ArcCoords[] = descriptors.map((desc) => {
      const fromX = anchorX.get(`${desc.link.id}:from`) ?? desc.from.rectLeft + desc.from.rectWidth / 2;
      const toX = anchorX.get(`${desc.link.id}:to`) ?? desc.to.rectLeft + desc.to.rectWidth / 2;
      const horizY = horizYByLink.get(String(desc.link.id)) ?? desc.edgeY + desc.sign * 4;
      const d = `M ${fromX},${desc.from.stubY} L ${fromX},${horizY} L ${toX},${horizY} L ${toX},${desc.to.stubY}`;
      return { link: desc.link, d };
    });

    setArcs(computed);
  }, [uniqueLinks, containerRef, tick]);

  if (!arcs.length) return null;

  return (
    <svg className={styles["link-arrow-overlay"]} aria-hidden="true">
      <defs>
        <marker id={MARKER_ID} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M 0 0 L 6 3 L 0 6 Z" fill={ARC_COLOR} />
        </marker>
      </defs>
      {arcs.map((arc) => {
        const isHighlighted = hoveredTermId === arc.link.from_term_id || hoveredTermId === arc.link.to_term_id;

        return (
          <path
            key={arc.link.id}
            d={arc.d}
            fill="none"
            stroke={ARC_COLOR}
            strokeWidth={1.5}
            markerEnd={`url(#${MARKER_ID})`}
            style={{
              opacity: interactive ? (isHighlighted ? 0.85 : 0.2) : 0.4,
              transition: "opacity 150ms ease",
              pointerEvents: interactive ? "stroke" : "none",
              cursor: interactive ? "default" : "inherit",
            }}
            onMouseEnter={interactive ? () => onHoverChange(arc.link.from_term_id) : undefined}
            onMouseLeave={interactive ? () => onHoverChange(null) : undefined}
          />
        );
      })}
    </svg>
  );
};

export default LinkArrowOverlay;
