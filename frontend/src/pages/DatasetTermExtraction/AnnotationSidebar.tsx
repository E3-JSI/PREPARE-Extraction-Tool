import React, { useEffect, useCallback, useState, useRef } from "react";
import classNames from "classnames";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronLeft, faChevronRight, faCheck } from "@fortawesome/free-solid-svg-icons";

import { format } from "date-fns";

import Sidebar from "@components/Sidebar";
import Button from "@components/Button";
import { getLabelColorClass } from "@/utils/labelColors";
import { tryParseWithDateFns } from "@/utils/dateUtils";
import AnnotatableText from "./AnnotatableText";

import type { SourceTerm, SourceTermCreate, LabelRelation, SourceTermLink } from "@/types";

import styles from "./styles.module.css";

export interface AnnotationSidebarProps {
  isOpen: boolean;
  text: string;
  labels: string[];
  labelRelations: LabelRelation[];
  selectedLabel: string | null;
  onSelectLabel: (label: string) => void;
  annotations: SourceTerm[];
  selectedAnnotation: number | null;
  onSelectAnnotation: (id: number | null) => void;
  onCreateAnnotation: (term: SourceTermCreate) => void;
  onDeleteAnnotation: (termId: number) => void;
  onUpdateAnnotationLabel?: (termId: number, newLabel: string) => void;
  onUpdateAnnotationDate?: (termId: number, newDate: string) => void;
  onCreateLink: (fromTermId: number, toTermId: number) => void;
  onDeleteLink: (linkId: number) => void;
  onClose: () => void;
  onPreviousRecord?: () => void;
  onNextRecord?: () => void;
  hasPreviousRecord?: boolean;
  hasNextRecord?: boolean;
  onMarkReviewed?: () => void;
  isReviewed?: boolean;
  readOnly?: boolean;
  recordInfo?: string;
}

const AnnotationSidebar: React.FC<AnnotationSidebarProps> = ({
  isOpen,
  text,
  labels,
  labelRelations,
  selectedLabel,
  onSelectLabel,
  annotations,
  selectedAnnotation,
  onSelectAnnotation,
  onCreateAnnotation,
  onDeleteAnnotation,
  onUpdateAnnotationDate,
  onCreateLink,
  onDeleteLink,
  onClose,
  onPreviousRecord,
  onNextRecord,
  hasPreviousRecord = true,
  hasNextRecord = true,
  onMarkReviewed,
  isReviewed = false,
  readOnly = false,
  recordInfo,
}) => {
  // Link mode state
  const [linkMode, setLinkMode] = useState(false);
  const [linkFromId, setLinkFromId] = useState<number | null>(null);

  const exitLinkMode = useCallback(() => {
    setLinkMode(false);
    setLinkFromId(null);
  }, []);

  // Returns the compatible partner label(s) for a given label
  const getCompatibleLabels = useCallback(
    (label: string): string[] => {
      const result: string[] = [];
      for (const rel of labelRelations) {
        if (rel.from_label === label) result.push(rel.to_label);
        if (rel.to_label === label) result.push(rel.from_label);
      }
      return result;
    },
    [labelRelations]
  );

  // Returns true if this label participates in any defined relation
  const isRelationLabel = useCallback(
    (label: string): boolean =>
      labelRelations.some((r: LabelRelation) => r.from_label === label || r.to_label === label),
    [labelRelations]
  );

  // Shared handler for span clicks and annotation list clicks in link mode
  const handleSpanLinkClick = useCallback(
    (termId: number) => {
      const annotation = annotations.find((a: SourceTerm) => a.id === termId);
      if (!annotation) return;

      if (linkFromId === null) {
        if (isRelationLabel(annotation.label)) setLinkFromId(termId);
      } else if (termId === linkFromId) {
        setLinkFromId(null);
      } else {
        const fromAnnotation = annotations.find((a: SourceTerm) => a.id === linkFromId);
        if (!fromAnnotation) return;
        const compatible = getCompatibleLabels(fromAnnotation.label).includes(annotation.label);
        if (!compatible) return;
        const existingLink = annotation.links?.find(
          (l: SourceTermLink) =>
            (l.from_term_id === linkFromId && l.to_term_id === termId) ||
            (l.to_term_id === linkFromId && l.from_term_id === termId)
        );
        if (existingLink) {
          onDeleteLink(existingLink.id);
        } else {
          onCreateLink(linkFromId, termId);
        }
        setLinkFromId(null);
      }
    },
    [annotations, linkFromId, isRelationLabel, getCompatibleLabels, onDeleteLink, onCreateLink]
  );

  // Handle label selection - either update selected annotation or select for new annotations
  const handleLabelSelection = useCallback(
    (label: string) => {
      if (selectedAnnotation !== null) return;
      onSelectLabel(label);
    },
    [selectedAnnotation, onSelectLabel]
  );

  // Local editing state for the date input so typing isn't immediately overwritten
  const [editingDate, setEditingDate] = useState<string>("");
  const [editingDateError, setEditingDateError] = useState<string | null>(null);
  const dateInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (selectedAnnotation !== null) {
      const ann = annotations.find((a) => a.id === selectedAnnotation);
      if (ann && ann.linked_visit_date) {
        const d = new Date(ann.linked_visit_date);
        const formatted = format(d, "dd/MM/yyyy");
        setEditingDate(formatted);
        setEditingDateError(null);
      } else {
        setEditingDate("");
        setEditingDateError(null);
      }
    } else {
      setEditingDate("");
      setEditingDateError(null);
    }
  }, [selectedAnnotation, annotations]);

  // Keyboard shortcuts for label selection (1-9)
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Don't handle if typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      // Escape exits link mode
      if (e.key === "Escape" && linkMode) {
        e.preventDefault();
        exitLinkMode();
        return;
      }

      // L toggles link mode (only when linking is available)
      if ((e.key === "l" || e.key === "L") && !readOnly && labelRelations.length > 0) {
        e.preventDefault();
        if (linkMode) {
          exitLinkMode();
        } else {
          setLinkMode(true);
          onSelectAnnotation(null);
        }
        return;
      }

      const key = parseInt(e.key, 10);
      if (!readOnly && !linkMode && key >= 1 && key <= 9 && key <= labels.length) {
        e.preventDefault();
        handleLabelSelection(labels[key - 1]);
      }

      // Delete/Backspace in link mode: remove all links of the selected "from" term
      if (linkMode && linkFromId !== null && (e.key === "Delete" || e.key === "Backspace")) {
        e.preventDefault();
        const fromTerm = annotations.find((a: SourceTerm) => a.id === linkFromId);
        if (fromTerm?.links && fromTerm.links.length > 0) {
          fromTerm.links.forEach((l: SourceTermLink) => onDeleteLink(l.id));
        }
        setLinkFromId(null);
        return;
      }

      // Delete selected annotation with Delete or Backspace (not in link mode)
      if (!readOnly && !linkMode && (e.key === "Delete" || e.key === "Backspace") && selectedAnnotation !== null) {
        e.preventDefault();
        onDeleteAnnotation(selectedAnnotation);
        onSelectAnnotation(null);
      }

      // Arrow Left - Previous record
      if (e.key === "ArrowLeft" && onPreviousRecord && hasPreviousRecord) {
        e.preventDefault();
        exitLinkMode();
        onPreviousRecord();
      }

      // Arrow Right - Next record
      if (e.key === "ArrowRight" && onNextRecord && hasNextRecord) {
        e.preventDefault();
        exitLinkMode();
        onNextRecord();
      }

      // Enter - Toggle reviewed status
      if (e.key === "Enter" && onMarkReviewed) {
        e.preventDefault();
        exitLinkMode();
        onMarkReviewed();
      }
    },
    [
      labels,
      labelRelations.length,
      handleLabelSelection,
      selectedAnnotation,
      onDeleteAnnotation,
      onSelectAnnotation,
      onPreviousRecord,
      onNextRecord,
      hasPreviousRecord,
      hasNextRecord,
      onMarkReviewed,
      readOnly,
      linkMode,
      linkFromId,
      annotations,
      onDeleteLink,
      exitLinkMode,
    ]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [isOpen, handleKeyDown]);

  return (
    <Sidebar isOpen={isOpen} onClose={onClose} title="Annotation Panel" width="75vw" disableEscapeClose={linkMode}>
      <div className={styles["annotation-sidebar"]} onClick={() => onSelectAnnotation(null)}>
        {/* Navigation row */}
        <div className={styles["annotation-nav"]}>
          <div className={styles["annotation-nav__pager"]}>
            <Button
              variant="outline"
              onClick={() => {
                exitLinkMode();
                onPreviousRecord?.();
              }}
              disabled={!onPreviousRecord || !hasPreviousRecord}
              title="Previous record"
            >
              <FontAwesomeIcon icon={faChevronLeft} />
              <span className={styles["record-navigation__button-text"]}>Previous</span>
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                exitLinkMode();
                onNextRecord?.();
              }}
              disabled={!onNextRecord || !hasNextRecord}
              title="Next record"
            >
              <span className={styles["record-navigation__button-text"]}>Next</span>
              <FontAwesomeIcon icon={faChevronRight} />
            </Button>
            {recordInfo && <span className={styles["annotation-nav__info"]}>{recordInfo}</span>}
          </div>
          <Button
            variant={isReviewed ? "success" : "primary"}
            onClick={() => {
              exitLinkMode();
              onMarkReviewed?.();
            }}
            disabled={!onMarkReviewed}
            title={isReviewed ? "Marked as reviewed" : "Mark as reviewed"}
          >
            {isReviewed ? <FontAwesomeIcon icon={faCheck} /> : null}
            <span className={styles["record-navigation__review-text"]}>
              {isReviewed ? "Reviewed" : "Mark as Reviewed"}
            </span>
          </Button>
        </div>

        {/* Condensed instructions */}
        <div className={styles["annotation-instructions"]}>
          {readOnly ? (
            <>
              <div>
                <strong>Read-only:</strong> this record is marked as reviewed — unmark it to edit annotations.
              </div>
              <div>
                <strong>Navigate:</strong> <kbd>←</kbd> / <kbd>→</kbd> previous / next record.
              </div>
              <div>
                <strong>Review:</strong> <kbd>Enter</kbd> toggles the reviewed status.
              </div>
            </>
          ) : (
            <>
              <div>
                <strong>Create:</strong> select a label, then highlight text in the record.
              </div>
              <div>
                <strong>Change label:</strong> click an annotation, then a label or <kbd>1</kbd>–<kbd>9</kbd>.
              </div>
              <div>
                <strong>Delete:</strong> click an annotation, press <kbd>Delete</kbd>.
              </div>
              {labelRelations.length > 0 && (
                <div>
                  <strong>Link:</strong> press <kbd>L</kbd>, click two compatible terms, <kbd>Esc</kbd> confirms.
                </div>
              )}
              <div>
                <strong>Navigate:</strong> <kbd>←</kbd> / <kbd>→</kbd> previous / next record.
              </div>
              <div>
                <strong>Review:</strong> <kbd>Enter</kbd> marks the record as reviewed.
              </div>
            </>
          )}
        </div>

        {/* Labels row */}
        <div className={styles["label-section"]}>
          <span className={styles["label-section__title"]}>Labels</span>
          {labels.map((label, index) => (
            <button
              key={label}
              className={classNames(styles["label-button"], styles[`label${index + 1}`], {
                [styles["label-button--active"]]: selectedLabel === label,
              })}
              onClick={() => handleLabelSelection(label)}
              disabled={readOnly || selectedAnnotation !== null || linkMode}
            >
              <span className={styles["label-button__shortcut"]}>{index + 1}</span>
              {label}
            </button>
          ))}
          {labels.length === 0 && <p className={styles["label-section__empty"]}>No labels defined for this dataset.</p>}
          {!readOnly && labelRelations.length > 0 && (
            <Button
              variant={linkMode ? "primary" : "outline"}
              size="small"
              className={styles["label-section__link-button"]}
              onClick={() => {
                if (linkMode) {
                  exitLinkMode();
                } else {
                  setLinkMode(true);
                  onSelectAnnotation(null);
                }
              }}
              title={
                linkMode
                  ? "Confirm linking (Esc)"
                  : "Link two annotations manually. Related terms are linked automatically during extraction when adjacent in the same sentence."
              }
            >
              {linkMode ? "Confirm" : "Link"}
            </Button>
          )}
        </div>
        {linkMode && (
          <div className={styles["link-mode-banner"]}>
            {linkFromId === null
              ? "Click a highlighted term in the text to select it"
              : "Click a compatible term in the text to link — or click a black term to unlink"}
          </div>
        )}

        {/* Main columns: record text + annotations */}
        <div className={styles["annotation-main"]}>
          <div className={styles["annotation-text"]}>
            <div className={styles["annotation-text__header"]}>
              <h3 className={styles["section-title"]}>Medical Record</h3>
              <span className={styles["annotation-text__help"]}>
                {selectedLabel ? (
                  <>
                    Highlight text to annotate as{" "}
                    <span
                      className={classNames(
                        styles["inline-label-badge"],
                        styles[getLabelColorClass(selectedLabel, labels)]
                      )}
                    >
                      {selectedLabel}
                    </span>
                  </>
                ) : (
                  "Select a label first, then highlight text"
                )}
              </span>
            </div>
            <div className={styles["annotation-text__content"]}>
              <AnnotatableText
                text={text}
                labels={labels}
                annotations={annotations}
                selectedLabel={selectedLabel}
                selectedAnnotation={selectedAnnotation}
                onCreateAnnotation={onCreateAnnotation}
                onSelectAnnotation={onSelectAnnotation}
                isAnnotating={!readOnly}
                linkMode={linkMode}
                linkFromId={linkFromId}
                onSpanLinkClick={handleSpanLinkClick}
                getCompatibleLabels={getCompatibleLabels}
                isRelationLabel={isRelationLabel}
              />
            </div>
          </div>

          <div className={styles["annotation-section"]}>
            <div className={styles["annotation-section__header"]}>
              <h3 className={styles["section-title"]}>Annotations ({annotations.length})</h3>
            </div>
            {annotations.length === 0 ? (
              <p className={styles["annotation-section__empty"]}>No annotations yet. Select text to create one.</p>
            ) : (
              <div className={styles["annotation-section__list"]}>
                {annotations.map((annotation) => {
                  return (
                    <div
                      key={annotation.id}
                      className={classNames(styles["annotation-item"], {
                        [styles["annotation-item--selected"]]: !linkMode && selectedAnnotation === annotation.id,
                      })}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (!readOnly && !linkMode) {
                          onSelectAnnotation(selectedAnnotation === annotation.id ? null : annotation.id);
                        }
                      }}
                    >
                      <div className={styles["annotation-item__row1"]}>
                        <span className={styles["annotation-item__value"]}>{annotation.value}</span>
                        <span
                          className={classNames(
                            styles["annotation-item__label"],
                            styles[getLabelColorClass(annotation.label, labels)]
                          )}
                        >
                          {annotation.label}
                        </span>
                        {!linkMode && (
                          <Button
                            variant="ghost"
                            size="icon"
                            colorScheme="danger"
                            className={styles["annotation-item__delete"]}
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteAnnotation(annotation.id);
                            }}
                            title="Delete annotation"
                            disabled={readOnly}
                          >
                            <svg
                              width="16"
                              height="16"
                              viewBox="0 0 16 16"
                              fill="none"
                              xmlns="http://www.w3.org/2000/svg"
                            >
                              <path
                                d="M2 4H14M5.333 4V2.667C5.333 2.298 5.632 2 6 2H10C10.368 2 10.667 2.298 10.667 2.667V4M12.667 4V13.333C12.667 13.702 12.368 14 12 14H4C3.632 14 3.333 13.702 3.333 13.333V4H12.667Z"
                                stroke="currentColor"
                                strokeWidth="1.5"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                            </svg>
                          </Button>
                        )}
                      </div>
                      <div className={styles["annotation-item__row2"]}>
                        {/* Date input for selected annotation (only outside link mode) */}
                        {!linkMode && selectedAnnotation === annotation.id ? (
                          <>
                            <input
                              type="text"
                              className={styles["annotation-item__date-input"]}
                              value={editingDate}
                              placeholder="DD/MM/YYYY"
                              onMouseDown={(e) => e.stopPropagation()}
                              onClick={(e) => e.stopPropagation()}
                              onFocus={(e) => e.stopPropagation()}
                              onChange={(e) => {
                                setEditingDate(e.target.value);
                                if (editingDateError) setEditingDateError(null);
                              }}
                              onBlur={() => {
                                const v = editingDate.trim();
                                if (v === "") {
                                  if (onUpdateAnnotationDate) onUpdateAnnotationDate(annotation.id, "");
                                  setEditingDateError(null);
                                  return;
                                }
                                const parsed = tryParseWithDateFns(v);
                                if (parsed) {
                                  const iso = format(parsed, "yyyy-MM-dd");
                                  if (onUpdateAnnotationDate) onUpdateAnnotationDate(annotation.id, iso);
                                  setEditingDate(format(parsed, "dd/MM/yyyy"));
                                  setEditingDateError(null);
                                } else {
                                  setEditingDateError("Unrecognized date format");
                                }
                              }}
                              ref={dateInputRef}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  dateInputRef.current?.blur();
                                }
                              }}
                            />
                            {editingDateError ? (
                              <span className={styles["annotation-item__date-error"]}>{editingDateError}</span>
                            ) : null}
                          </>
                        ) : (
                          <span className={styles["annotation-item__date"]}>
                            {annotation.linked_visit_date
                              ? new Date(annotation.linked_visit_date).toLocaleDateString("en-GB", {
                                  day: "2-digit",
                                  month: "2-digit",
                                  year: "numeric",
                                })
                              : "No date"}
                          </span>
                        )}
                        {annotation.linked_date_term_id &&
                          (() => {
                            const dateTerm = annotations.find((a) => a.id === annotation.linked_date_term_id);
                            if (!dateTerm) return null;
                            return (
                              <span className={styles["annotation-item__date-id"]}>↳ linked to {dateTerm.value}</span>
                            );
                          })()}
                      </div>
                      {/* Entity links */}
                      {annotation.links && annotation.links.length > 0 && (
                        <div className={styles["annotation-item__links"]}>
                          {annotation.links.map((link) => {
                            const isFrom = link.from_term_id === annotation.id;
                            const otherValue = isFrom ? link.to_term_value : link.from_term_value;
                            const otherLabel = isFrom ? link.to_term_label : link.from_term_label;
                            return (
                              <div key={link.id} className={styles["annotation-link-row"]}>
                                <span className={styles["annotation-link-row__direction"]}>{isFrom ? "→" : "←"}</span>
                                <span className={styles["annotation-link-row__value"]} title={otherValue}>
                                  {otherValue}
                                </span>
                                <span
                                  className={classNames(
                                    styles["annotation-item__label"],
                                    styles[getLabelColorClass(otherLabel, labels)]
                                  )}
                                >
                                  {otherLabel}
                                </span>
                                {!readOnly && !linkMode && (
                                  <button
                                    type="button"
                                    className={styles["annotation-link-row__delete"]}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onDeleteLink(link.id);
                                    }}
                                    title="Delete link"
                                  >
                                    ×
                                  </button>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </Sidebar>
  );
};

export default AnnotationSidebar;
