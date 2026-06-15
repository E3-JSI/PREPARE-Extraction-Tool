import React, { useRef, useMemo, useCallback, useState } from "react";
import classNames from "classnames";

import { getLabelColorClass } from "@/utils/labelColors";

import type { SourceTerm, SourceTermCreate, SourceTermLink } from "@/types";

import LinkArrowOverlay from "./LinkArrowOverlay";
import styles from "./styles.module.css";

export interface AnnotatableTextProps {
  text: string;
  labels: string[];
  annotations: SourceTerm[];
  selectedLabel: string | null;
  selectedAnnotation: number | null;
  onCreateAnnotation: (term: SourceTermCreate) => void;
  onSelectAnnotation: (id: number | null) => void;
  isAnnotating: boolean;
  // Link mode
  linkMode?: boolean;
  linkFromId?: number | null;
  onSpanLinkClick?: (termId: number) => void;
  getCompatibleLabels?: (label: string) => string[];
  isRelationLabel?: (label: string) => boolean;
}

const AnnotatableText: React.FC<AnnotatableTextProps> = ({
  text,
  labels,
  annotations,
  selectedLabel,
  selectedAnnotation,
  onCreateAnnotation,
  onSelectAnnotation,
  isAnnotating,
  linkMode = false,
  linkFromId = null,
  onSpanLinkClick,
  getCompatibleLabels,
  isRelationLabel,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredTermId, setHoveredTermId] = useState<number | null>(null);

  const hoveredConnectedIds = useMemo(() => {
    if (hoveredTermId === null) return new Set<number>();
    const connected = new Set<number>();
    for (const term of annotations) {
      for (const link of term.links ?? []) {
        if (link.from_term_id === hoveredTermId) connected.add(link.to_term_id);
        if (link.to_term_id === hoveredTermId) connected.add(link.from_term_id);
      }
    }
    connected.add(hoveredTermId);
    return connected;
  }, [hoveredTermId, annotations]);

  // Build segments from text and annotations
  const segments = useMemo(() => {
    if (!annotations.length) {
      return [{ type: "text" as const, content: text, start: 0, end: text.length }];
    }

    // Filter terms with valid positions and sort by start position
    const validTerms = annotations
      .filter((t) => t.start_position !== null && t.end_position !== null)
      .sort((a, b) => (a.start_position ?? 0) - (b.start_position ?? 0));

    if (!validTerms.length) {
      return [{ type: "text" as const, content: text, start: 0, end: text.length }];
    }

    const result: Array<
      | { type: "text"; content: string; start: number; end: number }
      | { type: "annotation"; content: string; term: SourceTerm; start: number; end: number }
    > = [];
    let lastEnd = 0;

    for (const term of validTerms) {
      const start = term.start_position ?? 0;
      const end = term.end_position ?? 0;

      // Skip overlapping terms
      if (start < lastEnd) continue;

      // Add text before this term
      if (start > lastEnd) {
        result.push({
          type: "text",
          content: text.slice(lastEnd, start),
          start: lastEnd,
          end: start,
        });
      }

      // Add the annotation
      result.push({
        type: "annotation",
        content: text.slice(start, end),
        term,
        start,
        end,
      });

      lastEnd = end;
    }

    // Add remaining text
    if (lastEnd < text.length) {
      result.push({
        type: "text",
        content: text.slice(lastEnd),
        start: lastEnd,
        end: text.length,
      });
    }

    return result;
  }, [text, annotations]);

  // Handle text selection
  const handleMouseUp = useCallback(() => {
    if (linkMode) return;
    if (!isAnnotating || !selectedLabel) return;

    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;

    const range = selection.getRangeAt(0);
    const container = containerRef.current;
    if (!container) return;

    // Check if selection is within our container
    if (!container.contains(range.commonAncestorContainer)) {
      return;
    }

    // Calculate the actual position in the original text
    // We need to traverse the DOM to find the correct offset
    const getTextOffset = (node: Node, offset: number): number => {
      let totalOffset = 0;
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
        acceptNode: (n) => {
          // Skip text inside aria-hidden elements (e.g. 🔗 badge) and SVG overlay
          let parent = n.parentElement;
          while (parent && parent !== container) {
            if (parent.getAttribute("aria-hidden") === "true") return NodeFilter.FILTER_REJECT;
            if (parent.tagName.toLowerCase() === "svg") return NodeFilter.FILTER_REJECT;
            parent = parent.parentElement;
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      });

      let currentNode: Node | null = walker.nextNode();
      while (currentNode) {
        if (currentNode === node) {
          return totalOffset + offset;
        }
        totalOffset += currentNode.textContent?.length ?? 0;
        currentNode = walker.nextNode();
      }
      return totalOffset;
    };

    // Get the selected text's position
    const startOffset = getTextOffset(range.startContainer, range.startOffset);
    const endOffset = getTextOffset(range.endContainer, range.endOffset);

    // Get the selected text value
    const selectedText = text.slice(startOffset, endOffset).trim();
    if (!selectedText) {
      selection.removeAllRanges();
      return;
    }

    // Adjust offsets for trimmed text
    const trimmedStart = startOffset + text.slice(startOffset, endOffset).indexOf(selectedText);
    const trimmedEnd = trimmedStart + selectedText.length;

    // Check for overlaps with existing annotations
    const hasOverlap = annotations.some((ann) => {
      if (ann.start_position === null || ann.end_position === null) return false;
      return trimmedStart < ann.end_position && trimmedEnd > ann.start_position;
    });

    if (hasOverlap) {
      selection.removeAllRanges();
      return;
    }

    // Create the annotation
    onCreateAnnotation({
      value: selectedText,
      label: selectedLabel,
      start_position: trimmedStart,
      end_position: trimmedEnd,
    });

    // Clear selection
    selection.removeAllRanges();
  }, [linkMode, isAnnotating, selectedLabel, text, annotations, onCreateAnnotation]);

  // Handle click on annotation
  const handleAnnotationClick = useCallback(
    (termId: number, e: React.MouseEvent) => {
      if (!isAnnotating) return;
      e.stopPropagation();
      onSelectAnnotation(selectedAnnotation === termId ? null : termId);
    },
    [isAnnotating, selectedAnnotation, onSelectAnnotation]
  );

  // Handle click on container to deselect
  const handleContainerClick = useCallback(() => {
    if (linkMode) return;
    if (selectedAnnotation !== null) {
      onSelectAnnotation(null);
    }
  }, [linkMode, selectedAnnotation, onSelectAnnotation]);

  // Pre-compute from-term once per render for link mode
  const linkFromTerm = linkMode && linkFromId != null
    ? annotations.find((a) => a.id === linkFromId) ?? null
    : null;

  return (
    <div
      ref={containerRef}
      className={classNames(styles['annotatable-text'], {
        [styles['annotatable-text--annotating']]: isAnnotating && !linkMode,
        [styles['annotatable-text--link-mode']]: linkMode,
      })}
      onMouseUp={handleMouseUp}
      onClick={handleContainerClick}
    >
      {segments.map((segment, idx) =>
        segment.type === "text" ? (
          <span key={idx}>{segment.content}</span>
        ) : (
          (() => {
            const term = segment.term;
            const isLinkFrom = linkMode && term.id === linkFromId;
            const compatibleWithFrom = linkFromTerm && getCompatibleLabels
              ? getCompatibleLabels(linkFromTerm.label).includes(term.label)
              : false;
            const termIsRelation = isRelationLabel ? isRelationLabel(term.label) : false;
            const isLinkable = linkMode && !isLinkFrom && (
              linkFromId === null ? termIsRelation : compatibleWithFrom
            );
            const isNotLinkable = linkMode && !isLinkFrom && (
              linkFromId === null ? !termIsRelation : !compatibleWithFrom
            );
            const alreadyLinked = linkMode && linkFromId !== null && compatibleWithFrom
              && !!term.links?.find(
                (l: SourceTermLink) =>
                  (l.from_term_id === linkFromId && l.to_term_id === term.id) ||
                  (l.to_term_id === linkFromId && l.from_term_id === term.id)
              );

            return (
              <span
                key={idx}
                data-term-id={term.id}
                className={classNames(
                  styles['highlighted-term'],
                  styles[getLabelColorClass(term.label, labels)],
                  {
                    [styles['highlighted-term--selected-annotation']]: !linkMode && selectedAnnotation === term.id,
                    [styles['highlighted-term--link-from']]: isLinkFrom,
                    [styles['highlighted-term--linkable']]: isLinkable && !alreadyLinked,
                    [styles['highlighted-term--already-linked']]: alreadyLinked,
                    [styles['highlighted-term--not-linkable']]: isNotLinkable,
                    [styles['highlighted-term--arc-hover']]: !linkMode && hoveredConnectedIds.has(term.id),
                  }
                )}
                title={`${term.label}: ${term.value}`}
                onMouseEnter={() => { if (!linkMode) setHoveredTermId(term.id); }}
                onMouseLeave={() => { if (!linkMode) setHoveredTermId(null); }}
                onClick={(e) => {
                  if (linkMode && onSpanLinkClick && !isNotLinkable) {
                    e.stopPropagation();
                    onSpanLinkClick(term.id);
                  } else {
                    handleAnnotationClick(term.id, e);
                  }
                }}
              >
                {segment.content}
                {term.links && term.links.length > 0 && (
                  <span className={styles['highlighted-term__link-badge']} aria-hidden="true">🔗</span>
                )}
              </span>
            );
          })()
        )
      )}
      {!linkMode && isAnnotating && !selectedLabel && (
        <div className={styles['annotatable-text__hint']}>Select a label from the sidebar to start annotating</div>
      )}
      <LinkArrowOverlay
        containerRef={containerRef}
        annotations={annotations}
        hoveredTermId={hoveredTermId}
        onHoverChange={setHoveredTermId}
        interactive={!linkMode}
      />
    </div>
  );
};

export default AnnotatableText;
