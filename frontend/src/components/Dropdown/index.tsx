import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";
import classNames from "classnames";
import styles from "./styles.module.css";

export interface DropdownItem {
  label: string;
  onClick: () => void;
  icon?: ReactNode;
  variant?: "default" | "danger";
  disabled?: boolean;
  title?: string;
}

export interface DropdownProps {
  trigger: ReactNode;
  items: DropdownItem[];
  align?: "left" | "right";
}

interface MenuPosition {
  top: number;
  left: number;
}

const Dropdown = ({ trigger, items, align = "right" }: DropdownProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState<MenuPosition>({ top: 0, left: 0 });

  const updatePosition = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    setMenuPosition({
      top: rect.bottom + 8,
      left: align === "right" ? rect.right : rect.left,
    });
  }, [align]);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current &&
        !triggerRef.current.contains(target) &&
        menuRef.current &&
        !menuRef.current.contains(target)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  // Close dropdown on escape key
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
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

  const handleItemClick = (item: DropdownItem) => {
    item.onClick();
    setIsOpen(false);
  };

  const menuStyle: React.CSSProperties = {
    top: menuPosition.top,
    left: menuPosition.left,
    // For right alignment, menuPosition.left holds the trigger's right edge;
    // shift the menu left by its own width so its right edge meets that point.
    ...(align === "right" ? { transform: "translateX(-100%)" } : {}),
  };

  const menu = isOpen && (
    <div ref={menuRef} className={styles.dropdown__menu} style={menuStyle}>
      {items.map((item, index) => (
        <button
          key={index}
          className={classNames(styles.dropdown__item, {
            [styles["dropdown__item--danger"]]: item.variant === "danger",
          })}
          onClick={() => handleItemClick(item)}
          type="button"
          disabled={item.disabled}
          title={item.title}
        >
          {item.icon && <span className={styles["dropdown__item-icon"]}>{item.icon}</span>}
          {item.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className={styles.dropdown}>
      <div ref={triggerRef} className={styles.dropdown__trigger} onClick={() => setIsOpen(!isOpen)}>
        {trigger}
      </div>

      {menu && createPortal(menu, document.body)}
    </div>
  );
};

export default Dropdown;
