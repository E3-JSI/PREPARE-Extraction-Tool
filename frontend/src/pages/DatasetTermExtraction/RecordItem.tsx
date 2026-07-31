import React from "react";
import classNames from "classnames";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck } from "@fortawesome/free-solid-svg-icons";

import type { Record as RecordType } from "@/types";

import styles from "./styles.module.css";

interface RecordItemProps {
  record: RecordType;
  isSelected: boolean;
  onClick: () => void;
}

const RecordItem: React.FC<RecordItemProps> = ({ record, isSelected, onClick }) => {
  const snippet = record.text.split("\n").find((line) => line.trim().length > 0)?.trim() ?? "";

  return (
    <div
      className={classNames(styles["record-item"], { [styles["record-item--selected"]]: isSelected })}
      onClick={onClick}
      title={record.text.slice(0, 150)}
    >
      <div className={styles["record-item__main"]}>
        <div className={styles["record-item__id"]}>{record.patient_id}</div>
        {snippet && <div className={styles["record-item__snippet"]}>{snippet}</div>}
        <div className={styles["record-item__meta"]}>
          {record.seq_number ? `#${record.seq_number} · ` : ""}
          {record.source_term_count > 0
            ? `${record.source_term_count} term${record.source_term_count !== 1 ? "s" : ""}`
            : "No terms"}
        </div>
      </div>
      {record.reviewed && <FontAwesomeIcon icon={faCheck} className={styles["record-item__check"]} title="Reviewed" />}
    </div>
  );
};

export default RecordItem;
