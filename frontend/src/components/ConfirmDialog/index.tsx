import React, { useEffect, useRef, useState, useCallback } from "react";
import Button from "@components/Button";
import styles from "./styles.module.css";

export type DialogVariant = "danger" | "warning" | "info";

export interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  onConfirm: (inputValue?: string) => void;
  onCancel: () => void;
  variant?: DialogVariant;
  confirmText?: string;
  cancelText?: string;
  showInput?: boolean;
  inputPlaceholder?: string;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  onConfirm,
  onCancel,
  variant = "info",
  confirmText = "Confirm",
  cancelText = "Cancel",
  showInput = false,
  inputPlaceholder = "",
}) => {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [inputValue, setInputValue] = useState("");

  // Scroll-lock while the dialog is open (keyed on isOpen only)
  useEffect(() => {
    if (!isOpen) return;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  // Reset input, capture/restore focus when opening/closing
  useEffect(() => {
    if (isOpen) {
      setInputValue("");
      previousActiveElement.current = document.activeElement as HTMLElement;
      if (showInput) {
        setTimeout(() => inputRef.current?.focus(), 0);
      } else {
        confirmButtonRef.current?.focus();
      }
      return () => {
        previousActiveElement.current?.focus();
      };
    }
  }, [isOpen, showInput]);

  // Handle keyboard events
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === "Escape") {
        onCancel();
        return;
      }

      // Focus trap
      if (e.key === "Tab" && dialogRef.current) {
        const focusableElements = dialogRef.current.querySelectorAll<HTMLElement>(
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
    },
    [isOpen, onCancel]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  if (!isOpen) return null;

  return (
    <>
      <div className={styles["confirm-dialog__backdrop"]} onClick={onCancel} aria-hidden="true" />
      <div
        ref={dialogRef}
        className={styles["confirm-dialog"]}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
      >
        <h2 id="confirm-dialog-title" className={styles["confirm-dialog__title"]}>
          {title}
        </h2>
        <p id="confirm-dialog-message" className={styles["confirm-dialog__message"]}>
          {message}
        </p>
        {showInput && (
          <input
            ref={inputRef}
            type="text"
            className={styles["confirm-dialog__input"]}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={inputPlaceholder}
            onKeyDown={(e) => {
              if (e.key === "Enter" && inputValue.trim()) {
                onConfirm(inputValue.trim());
              }
            }}
          />
        )}
        <div className={styles["confirm-dialog__actions"]}>
          <Button variant="outline" onClick={onCancel}>
            {cancelText}
          </Button>
          <Button
            ref={confirmButtonRef}
            variant={variant === "danger" ? "danger" : variant === "warning" ? "warning" : "info"}
            onClick={() => onConfirm(showInput ? inputValue.trim() : undefined)}
            disabled={showInput && !inputValue.trim()}
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </>
  );
};

export default ConfirmDialog;
