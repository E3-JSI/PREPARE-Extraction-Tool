import type { IconProp } from "@fortawesome/fontawesome-svg-core";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

import Button from "@components/Button";

import styles from "./styles.module.css";

interface WorkflowCardProps {
  title: string;
  description: string;
  icon?: IconProp;
  stats: Array<{ label: string; value: string | number }>;
  progress?: { current: number; total: number };
  actions: Array<{ label: string; onClick: () => void; variant?: "primary" | "secondary"; disabled?: boolean }>;
}

const WorkflowCard = ({ title, description, icon, stats, progress, actions }: WorkflowCardProps) => {
  const progressPercentage = progress && progress.total > 0 ? (progress.current / progress.total) * 100 : 0;

  return (
    <div className={styles["workflow-card"]}>
      <div className={styles["workflow-card__header"]}>
        <div>
          <h3 className={styles["workflow-card__title"]}>{title}</h3>
          <p className={styles["workflow-card__description"]}>{description}</p>
        </div>
        {icon && <FontAwesomeIcon icon={icon} className={styles["workflow-card__icon"]} />}
      </div>

      <div className={styles["workflow-card__stats"]}>
        {stats.map((stat, idx) => (
          <div key={idx} className={styles["workflow-card__stat"]}>
            <span className={styles["workflow-card__stat-label"]}>{stat.label}</span>
            <span className={styles["workflow-card__stat-value"]}>{stat.value}</span>
          </div>
        ))}
      </div>

      {progress && (
        <div className={styles["workflow-card__progress"]}>
          <div className={styles["workflow-card__progress-header"]}>
            <span className={styles["workflow-card__progress-label"]}>Progress</span>
            <span className={styles["workflow-card__progress-text"]}>
              {progress.current} / {progress.total} ({Math.round(progressPercentage)}%)
            </span>
          </div>
          <div className={styles["workflow-card__progress-bar"]}>
            <div
              className={styles["workflow-card__progress-fill"]}
              style={{ width: `${Math.min(100, progressPercentage)}%` }}
            />
          </div>
        </div>
      )}

      <div className={styles["workflow-card__actions"]}>
        {actions.map((action, idx) => (
          <Button
            key={idx}
            onClick={action.onClick}
            variant={action.variant === "primary" ? "primary" : "outline"}
            className={styles["workflow-card__button"]}
            disabled={action.disabled ?? false}
          >
            {action.label}
          </Button>
        ))}
      </div>
    </div>
  );
};

export default WorkflowCard;
