import React, { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import classNames from "classnames";
import styles from "./styles.module.css";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  options: SelectOption[];
  placeholder?: string;

  // Single select
  value?: string;
  onValueChange?: (value: string) => void;

  // Multi select
  multiSelect?: boolean;
  values?: string[];
  onValuesChange?: (values: string[]) => void;

  // Optional filter mode (shows checkbox when provided)
  label?: string;
  enabled?: boolean;
  onEnabledChange?: (enabled: boolean) => void;

  // Additional props for flexibility
  size?: "small" | "medium";
  fullWidth?: boolean;
  disabled?: boolean;
  className?: string;
  id?: string;
  "aria-label"?: string;
}

interface MenuPosition {
  top: number;
  left: number;
  width: number;
}

export const Select: React.FC<SelectProps> = ({
  options,
  placeholder = "Select...",
  value,
  onValueChange,
  multiSelect = false,
  values = [],
  onValuesChange,
  label,
  enabled = true,
  onEnabledChange,
  size = "medium",
  fullWidth = true,
  disabled = false,
  className,
  id,
  "aria-label": ariaLabel,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState<MenuPosition>({ top: 0, left: 0, width: 0 });

  // Determine if filter mode is active (shows checkbox header)
  const isFilterMode = label !== undefined && onEnabledChange !== undefined;

  // Combined disabled state
  const isDisabled = disabled || (isFilterMode && !enabled);

  const updatePosition = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    setMenuPosition({
      top: rect.bottom + 4,
      left: rect.left,
      width: rect.width,
    });
  }, []);

  // Close dropdown on click outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        containerRef.current &&
        !containerRef.current.contains(target) &&
        menuRef.current &&
        !menuRef.current.contains(target)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  // Reposition on scroll/resize while open
  useEffect(() => {
    if (!isOpen) return;
    updatePosition();

    const handleScrollOrResize = () => updatePosition();

    window.addEventListener("scroll", handleScrollOrResize, true);
    window.addEventListener("resize", handleScrollOrResize);
    return () => {
      window.removeEventListener("scroll", handleScrollOrResize, true);
      window.removeEventListener("resize", handleScrollOrResize);
    };
  }, [isOpen, updatePosition]);

  const handleToggle = () => {
    if (!isDisabled) {
      setIsOpen(!isOpen);
    }
  };

  const handleSingleSelect = (optionValue: string) => {
    if (onValueChange) {
      onValueChange(optionValue);
    }
    setIsOpen(false);
  };

  const handleMultiSelect = (optionValue: string) => {
    if (!onValuesChange) return;

    if (values.includes(optionValue)) {
      onValuesChange(values.filter((v) => v !== optionValue));
    } else {
      onValuesChange([...values, optionValue]);
    }
  };

  const getDisplayText = () => {
    if (multiSelect) {
      if (values.length === 0) return placeholder;
      if (values.length === 1) {
        const option = options.find((o) => o.value === values[0]);
        return option?.label || values[0];
      }
      return `${values.length} selected`;
    } else {
      if (!value) return placeholder;
      const option = options.find((o) => o.value === value);
      return option?.label || value;
    }
  };

  const containerClasses = classNames(
    {
      [styles["select--disabled"]]: isDisabled,
      [styles["select--small"]]: size === "small",
      [styles["select--full-width"]]: fullWidth,
    },
    className
  );

  const menuClasses = classNames(styles.select__menu, {
    [styles["select__menu--small"]]: size === "small",
  });

  const menu = isOpen && !isDisabled && (
    <div
      ref={menuRef}
      className={menuClasses}
      role="listbox"
      style={{
        top: menuPosition.top,
        left: menuPosition.left,
        minWidth: menuPosition.width,
      }}
    >
      {options.length === 0 ? (
        <div className={styles.select__empty}>No options available</div>
      ) : (
        options.map((option) => (
          <div
            key={option.value}
            className={classNames(styles.select__option, {
              [styles["select__option--selected"]]: multiSelect
                ? values.includes(option.value)
                : value === option.value,
            })}
            onClick={() => (multiSelect ? handleMultiSelect(option.value) : handleSingleSelect(option.value))}
            role="option"
            aria-selected={multiSelect ? values.includes(option.value) : value === option.value}
          >
            {multiSelect && (
              <input
                type="checkbox"
                checked={values.includes(option.value)}
                onChange={() => handleMultiSelect(option.value)}
                className={styles["select__option-checkbox"]}
                onClick={(e) => e.stopPropagation()}
              />
            )}
            <span className={styles["select__option-label"]}>{option.label}</span>
          </div>
        ))
      )}
    </div>
  );

  return (
    <div ref={containerRef} className={containerClasses} id={id}>
      {isFilterMode && (
        <div className={styles.select__header}>
          <label className={styles["select__checkbox-label"]}>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => onEnabledChange?.(e.target.checked)}
              className={styles.select__checkbox}
            />
            <span className={styles.select__label}>{label}</span>
          </label>
        </div>
      )}

      <button
        ref={triggerRef}
        type="button"
        className={styles.select__trigger}
        onClick={handleToggle}
        disabled={isDisabled}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
      >
        <span className={styles["select__trigger-text"]}>{getDisplayText()}</span>
        <span className={styles.select__arrow}>{isOpen ? "▲" : "▼"}</span>
      </button>

      {menu && createPortal(menu, document.body)}
    </div>
  );
};

export default Select;
