import classNames from "classnames";

import styles from "./styles.module.css";

export interface ProgressBarProps {
  /** Progress value between 0 and 100 (alias of `progress`) */
  value?: number;
  /** Progress value between 0 and 100 (legacy prop) */
  progress?: number;
  /** Optional label rendered above the bar */
  label?: string;
  /** Whether to render the trailing percentage (legacy layout) */
  showPercentage?: boolean;
  /** Additional class names for the wrapper */
  className?: string;
}

const ProgressBar = ({ value, progress, label, showPercentage = true, className }: ProgressBarProps) => {
  const raw = value ?? progress ?? 0;
  const clamped = Math.min(Math.max(raw, 0), 100);

  return (
    <div className={classNames(styles["progress-bar"], className)}>
      {label && <span className={styles["progress-bar__label"]}>{label}</span>}
      <div className={styles["progress-bar__track"]}>
        <div className={styles["progress-bar__fill"]} style={{ width: `${clamped}%` }} />
      </div>
      {showPercentage && <span className={styles["progress-bar__percentage"]}>{Math.round(clamped)}%</span>}
    </div>
  );
};

export default ProgressBar;
