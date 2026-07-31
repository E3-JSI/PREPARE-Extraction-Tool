import { useEffect, useRef } from "react";
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
  const asideRef = useRef<HTMLElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === "Escape" && !disableEscapeClose) {
        onClose();
        return;
      }

      // Focus trap
      if (e.key === "Tab" && asideRef.current) {
        const focusableElements = asideRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusableElements.length === 0) return;

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey && document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        } else if (!e.shiftKey && document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose, disableEscapeClose]);

  // Capture/restore focus and move focus into the drawer when opening
  useEffect(() => {
    if (isOpen) {
      previousActiveElement.current = document.activeElement as HTMLElement;
      const firstFocusable = asideRef.current?.querySelector<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      firstFocusable?.focus();
      return () => {
        previousActiveElement.current?.focus();
      };
    }
  }, [isOpen]);

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
        ref={asideRef}
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
