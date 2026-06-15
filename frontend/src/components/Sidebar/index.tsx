import { useEffect } from "react";
import classNames from "classnames";

import Button from "@components/Button";

import styles from "./styles.module.css";

export interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  width?: string;
  children: React.ReactNode;
  disableEscapeClose?: boolean;
}

const Sidebar = ({ isOpen, onClose, title, width = "400px", children, disableEscapeClose = false }: SidebarProps) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !disableEscapeClose) {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose, disableEscapeClose]);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  return (
    <>
      <div
        className={classNames(styles["sidebar__backdrop"], {
          [styles["sidebar__backdrop--visible"]]: isOpen,
        })}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className={classNames(styles.sidebar, {
          [styles["sidebar--open"]]: isOpen,
        })}
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className={styles["sidebar__header"]}>
          <h2 className={styles["sidebar__title"]}>{title}</h2>
          <Button
            variant="ghost"
            size="icon"
            className={styles["sidebar__close-button"]}
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M15 5L5 15M5 5L15 15"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Button>
        </header>
        <div className={styles["sidebar__content"]}>{children}</div>
      </aside>
    </>
  );
};

export default Sidebar;
