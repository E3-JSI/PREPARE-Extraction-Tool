import React, { useMemo, useRef, useState } from "react";
import classNames from "classnames";

import { getLabelColorClass } from "@/utils/labelColors";

import type { SourceTerm } from "@/types";

import LinkArrowOverlay from "./LinkArrowOverlay";
import styles from "./styles.module.css";

interface HighlightedTextProps {
  text: string;
  terms: SourceTerm[];
  labels: string[];
  focusedTermId?: number | null;
}

const HighlightedText: React.FC<HighlightedTextProps> = ({ text, terms, labels, focusedTermId }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredTermId, setHoveredTermId] = useState<number | null>(null);

  const segments = useMemo(() => {
    if (!terms.length) {
      return [{ type: "text" as const, content: text }];
    }

    const validTerms = terms
      .filter((t) => t.start_position !== null && t.end_position !== null)
      .sort((a, b) => (a.start_position ?? 0) - (b.start_position ?? 0));

    if (!validTerms.length) {
      return [{ type: "text" as const, content: text }];
    }

    const result: Array<{ type: "text"; content: string } | { type: "term"; content: string; term: SourceTerm }> = [];
    let lastEnd = 0;

    for (const term of validTerms) {
      const start = term.start_position ?? 0;
      const end = term.end_position ?? 0;

      if (start < lastEnd) continue;

      if (start > lastEnd) {
        result.push({ type: "text", content: text.slice(lastEnd, start) });
      }

      result.push({ type: "term", content: text.slice(start, end), term });

      lastEnd = end;
    }

    if (lastEnd < text.length) {
      result.push({ type: "text", content: text.slice(lastEnd) });
    }

    return result;
  }, [text, terms]);

  const hoveredConnectedIds = useMemo(() => {
    if (hoveredTermId === null) return new Set<number>();
    const connected = new Set<number>();
    for (const term of terms) {
      for (const link of term.links ?? []) {
        if (link.from_term_id === hoveredTermId) connected.add(link.to_term_id);
        if (link.to_term_id === hoveredTermId) connected.add(link.from_term_id);
      }
    }
    connected.add(hoveredTermId);
    return connected;
  }, [hoveredTermId, terms]);

  return (
    <div className={styles['record-text']} ref={containerRef}>
      {segments.map((segment, idx) =>
        segment.type === "text" ? (
          <span key={idx}>{segment.content}</span>
        ) : (
          <span
            key={idx}
            data-term-id={segment.term.id}
            className={classNames(styles['highlighted-term'], styles[getLabelColorClass(segment.term.label, labels)], {
              [styles['highlighted-term--focused']]: focusedTermId === segment.term.id,
              [styles['highlighted-term--arc-hover']]: hoveredConnectedIds.has(segment.term.id),
            })}
            title={
              segment.term.links && segment.term.links.length > 0
                ? `${segment.term.label}: ${segment.term.value}\nLinked to: ${segment.term.links
                    .map((l) =>
                      l.from_term_id === segment.term.id ? l.to_term_value : l.from_term_value
                    )
                    .join(", ")}`
                : `${segment.term.label}: ${segment.term.value}`
            }
            onMouseEnter={() => setHoveredTermId(segment.term.id)}
            onMouseLeave={() => setHoveredTermId(null)}
          >
            {segment.content}
            {segment.term.links && segment.term.links.length > 0 && (
              <span className={styles['highlighted-term__link-badge']} aria-hidden="true">
                🔗
              </span>
            )}
          </span>
        )
      )}
      <LinkArrowOverlay
        containerRef={containerRef}
        annotations={terms}
        hoveredTermId={hoveredTermId}
        onHoverChange={setHoveredTermId}
      />
    </div>
  );
};

export default HighlightedText;
