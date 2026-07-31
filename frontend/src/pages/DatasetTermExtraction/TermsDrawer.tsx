import React from "react";
import classNames from "classnames";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronRight } from "@fortawesome/free-solid-svg-icons";

import Button from "@components/Button";
import { getLabelColorClass } from "@/utils/labelColors";

import type { SourceTerm } from "@/types";

import styles from "./styles.module.css";

interface TermsDrawerProps {
  isOpen: boolean;
  onToggle: (open: boolean) => void;
  terms: SourceTerm[];
  labels: string[];
  /** Term card to flash-highlight (set when a text highlight is clicked) */
  flashedTermId: number | null;
  /** Scroll the record text to this term's highlight */
  onTermClick: (termId: number) => void;
}

const formatDate = (isoDate: string) =>
  new Date(isoDate).toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit", year: "numeric" });

const TermsDrawer: React.FC<TermsDrawerProps> = ({ isOpen, onToggle, terms, labels, flashedTermId, onTermClick }) => {
  if (!isOpen) {
    return (
      <aside className={classNames(styles["terms-drawer"], styles["terms-drawer--closed"])}>
        <button className={styles["terms-drawer__tab"]} onClick={() => onToggle(true)} title="Show extracted terms">
          Terms · {terms.length}
        </button>
      </aside>
    );
  }

  return (
    <aside className={styles["terms-drawer"]}>
      <div className={styles["terms-drawer__header"]}>
        <h2 className={styles["terms-drawer__title"]}>Extracted Terms ({terms.length})</h2>
        <Button variant="ghost" size="icon" onClick={() => onToggle(false)} title="Collapse terms drawer">
          <FontAwesomeIcon icon={faChevronRight} />
        </Button>
      </div>
      <div className={styles["terms-drawer__list"]}>
        {terms.length === 0 ? (
          <div className={styles["empty-state"]}>
            <p className={styles["empty-state__text"]}>No terms extracted</p>
            <p className={styles["empty-state__subtext"]}>Run NER extraction to identify terms</p>
          </div>
        ) : (
          terms.map((term) => {
            const linkedDateTerm = term.linked_date_term_id
              ? terms.find((t) => t.id === term.linked_date_term_id)
              : undefined;
            return (
              <div
                key={term.id}
                data-drawer-term-id={term.id}
                className={classNames(styles["annotation-item"], {
                  [styles["annotation-item--flash"]]: flashedTermId === term.id,
                })}
                onClick={() => onTermClick(term.id)}
              >
                <div className={styles["annotation-item__row1"]}>
                  <span className={styles["annotation-item__value"]} title={term.value}>
                    {term.value}
                  </span>
                  <span
                    className={classNames(
                      styles["annotation-item__label"],
                      styles[getLabelColorClass(term.label, labels)]
                    )}
                  >
                    {term.label}
                  </span>
                </div>
                <div className={styles["annotation-item__row2"]}>
                  <span className={styles["annotation-item__date"]}>
                    {term.linked_visit_date ? formatDate(term.linked_visit_date) : "No date"}
                  </span>
                  {linkedDateTerm && (
                    <span className={styles["annotation-item__date-id"]} title={`Linked to ${linkedDateTerm.value}`}>
                      ↳ linked to {linkedDateTerm.value}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
};

export default TermsDrawer;
