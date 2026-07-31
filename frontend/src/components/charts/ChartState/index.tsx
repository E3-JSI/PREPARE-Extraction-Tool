import React from "react";

import LoadingSpinner from "@components/LoadingSpinner";

import styles from "./styles.module.css";

export type ChartStateVariant = "loading" | "empty" | "error";

export interface ChartStateProps {
  variant: ChartStateVariant;
  /** Short headline (ignored for the loading variant). */
  title?: string;
  /** Supporting message. */
  message?: string;
  /** Optional icon/illustration shown above the title. */
  icon?: React.ReactNode;
  /** Optional call-to-action (e.g. a Button) shown below the message. */
  action?: React.ReactNode;
  /** Min-height so the placeholder occupies the chart's footprint. */
  height?: number;
}

/**
 * Uniform placeholder for the non-happy chart paths (loading / empty / error).
 * Used by the monitoring domain wrappers so every chart degrades consistently.
 */
const ChartState = ({ variant, title, message, icon, action, height = 250 }: ChartStateProps) => {
  if (variant === "loading") {
    return (
      <div className={styles.state} style={{ minHeight: height }}>
        <LoadingSpinner text={message ?? "Loading…"} />
      </div>
    );
  }

  return (
    <div className={styles.state} style={{ minHeight: height }} data-variant={variant}>
      {icon && <div className={styles.state__icon}>{icon}</div>}
      {title && <p className={styles.state__title}>{title}</p>}
      {message && <p className={styles.state__message}>{message}</p>}
      {action && <div className={styles.state__action}>{action}</div>}
    </div>
  );
};

export default ChartState;
