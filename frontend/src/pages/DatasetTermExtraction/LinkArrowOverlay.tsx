import React, { useEffect, useMemo, useState } from "react";

import type { SourceTerm, SourceTermLink } from "@/types";

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
    const computed: ArcCoords[] = [];

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

      // X anchors use the center of the relevant line box, not the union bounding box
      const x1First = fromFirst.left + fromFirst.width / 2 - containerRect.left;
      const x1Last  = fromLast.left  + fromLast.width  / 2 - containerRect.left;
      const x2First = toFirst.left   + toFirst.width   / 2 - containerRect.left;
      const x2Last  = toLast.left    + toLast.width    / 2 - containerRect.left;

      const sameLine = Math.abs(y1Top - y2Top) < SAME_LINE_THRESHOLD;

      let d: string;
      if (sameLine) {
        // Horizontal sits 4px above the spans — in the inter-line gap above current line
        const arcTopY = Math.min(y1Top, y2Top) - 4;
        d = `M ${x1First},${y1Top} L ${x1First},${arcTopY} L ${x2First},${arcTopY} L ${x2First},${y2Top}`;
      } else if (y1Top < y2Top) {
        // Forward: horizontal sits 4px below from-span — in the inter-line gap
        const horizY = y1Bot + 4;
        d = `M ${x1Last},${y1Bot} L ${x1Last},${horizY} L ${x2First},${horizY} L ${x2First},${y2Top}`;
      } else {
        // Backward: horizontal sits 4px above from-span — in the inter-line gap
        const horizY = y1Top - 4;
        d = `M ${x1First},${y1Top} L ${x1First},${horizY} L ${x2Last},${horizY} L ${x2Last},${y2Bot}`;
      }

      computed.push({ link, d });
    }

    setArcs(computed);
  }, [uniqueLinks, containerRef, tick]);

  if (!arcs.length) return null;

  return (
    <svg className={styles["link-arrow-overlay"]} aria-hidden="true">
      <defs>
        <marker
          id={MARKER_ID}
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path d="M 0 0 L 6 3 L 0 6 Z" fill={ARC_COLOR} />
        </marker>
      </defs>
      {arcs.map((arc) => {
        const isHighlighted =
          hoveredTermId === arc.link.from_term_id ||
          hoveredTermId === arc.link.to_term_id;

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
