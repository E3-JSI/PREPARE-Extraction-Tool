import React from "react";
import { Link } from "react-router-dom";
import styles from "./styles.module.css";

interface ActiveModelChipProps {
  modelName: string;
}

const ActiveModelChip: React.FC<ActiveModelChipProps> = ({ modelName }) => {
  return (
    <span className={styles.caption} title="Extraction model used by Auto-Detect (set in Monitor)">
      using <span className={styles["caption__name"]}>{modelName}</span>
      {" · "}
      <Link to="/monitor" className={styles["caption__link"]}>
        change in Monitor ↗
      </Link>
    </span>
  );
};

export default ActiveModelChip;
