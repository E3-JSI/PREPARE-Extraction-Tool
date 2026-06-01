import React from "react";
import classNames from "classnames";

import styles from "./styles.module.css";

interface LoadingSpinnerProps {
  size?: "small" | "medium" | "large";
  text?: string;
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ size = "medium", text }) => {
  return (
    <div className={styles["loading-spinner"]} role="status" aria-label={text || "Loading"}>
      <div className={classNames(styles["loading-spinner__spinner"], styles[`loading-spinner__spinner--${size}`])} />
      {text && <span className={styles["loading-spinner__text"]}>{text}</span>}
    </div>
  );
};

export default LoadingSpinner;
