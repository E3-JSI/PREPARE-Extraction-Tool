import styles from "./styles.module.css";

export interface ProgressBarProps {
  progress: number; // 0-100
  showPercentage?: boolean;
}

const ProgressBar = ({ progress, showPercentage = true }: ProgressBarProps) => {
  const clampedProgress = Math.min(Math.max(progress, 0), 100);

  return (
    <div className={styles["progress-bar"]}>
      <div className={styles["progress-bar__track"]}>
        <div className={styles["progress-bar__fill"]} style={{ width: `${clampedProgress}%` }} />
      </div>
      {showPercentage && <span className={styles["progress-bar__percentage"]}>{Math.round(clampedProgress)}%</span>}
    </div>
  );
};

export default ProgressBar;
