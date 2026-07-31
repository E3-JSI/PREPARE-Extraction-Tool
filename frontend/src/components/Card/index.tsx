import React from "react";
import classNames from "classnames";

import styles from "./styles.module.css";

export interface CardProps {
  /** Optional card title rendered in the header */
  title?: string;
  /** Optional actions rendered in the header */
  actions?: React.ReactNode;
  /** Additional class names for the card container */
  className?: string;
  /** Card content */
  children: React.ReactNode;
}

/** Container component for grouping related content with an optional header. */
const Card: React.FC<CardProps> = ({ title, actions, className, children }) => {
  return (
    <section className={classNames(styles.card, className)}>
      {(title || actions) && (
        <div className={styles.card__header}>
          {title && <h2 className={styles.card__title}>{title}</h2>}
          {actions}
        </div>
      )}
      <div className={styles.card__body}>{children}</div>
    </section>
  );
};

export default Card;
