import classNames from "classnames";
import styles from "./styles.module.css";

interface StatCardProps {
  label: string;
  value: string | number;
  /** Optional muted secondary line rendered under the label (e.g. "of 120 in dataset"). */
  subtext?: string;
  color?: "default" | "blue" | "green" | "orange";
  className?: string;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, subtext, color = "default", className }) => {
  return (
    <div className={classNames(styles["stat-card"], className)}>
      <div
        className={classNames(styles["stat-card__value"], {
          [styles["stat-card__value--blue"]]: color === "blue",
          [styles["stat-card__value--green"]]: color === "green",
          [styles["stat-card__value--orange"]]: color === "orange",
        })}
      >
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div className={styles["stat-card__meta"]}>
        <div className={styles["stat-card__label"]}>{label}</div>
        {subtext && <div className={styles["stat-card__subtext"]}>{subtext}</div>}
      </div>
    </div>
  );
};

export default StatCard;
