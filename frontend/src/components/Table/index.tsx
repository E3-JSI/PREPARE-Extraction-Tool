import classNames from "classnames";

import LoadingSpinner from "@components/LoadingSpinner";

import styles from "./styles.module.css";

export interface Column<T> {
  key: keyof T | string;
  header: string;
  width?: string;
  render?: (item: T) => React.ReactNode;
  sortable?: boolean;
  align?: "left" | "center" | "right";
}

export interface SortState {
  key: string;
  direction: "asc" | "desc";
}

export interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (item: T, index: number) => string | number;
  emptyMessage?: string;
  onRowClick?: (item: T) => void;
  isRowSelected?: (item: T) => boolean;
  isLoading?: boolean;
  loadingContent?: React.ReactNode;
  isLoadingOverlay?: boolean;
  sort?: SortState;
  onSortChange?: (key: string) => void;
  stickyHeader?: boolean;
  ariaLabel?: string;
  className?: string;
}

function Table<T>({
  columns,
  data,
  keyExtractor,
  emptyMessage = "No data available",
  onRowClick,
  isRowSelected,
  isLoading = false,
  loadingContent,
  isLoadingOverlay = false,
  sort,
  onSortChange,
  stickyHeader = false,
  ariaLabel,
  className,
}: TableProps<T>) {
  const getCellValue = (item: T, column: Column<T>): React.ReactNode => {
    if (column.render) {
      return column.render(item);
    }
    const value = item[column.key as keyof T];
    if (value === null || value === undefined) {
      return "-";
    }
    return String(value);
  };

  const handleHeaderClick = (column: Column<T>) => {
    if (column.sortable && onSortChange) {
      onSortChange(String(column.key));
    }
  };

  const renderSortIcon = (column: Column<T>) => {
    if (!column.sortable) return null;
    if (!sort || sort.key !== String(column.key)) {
      return <span className={styles["table__sort-icon"]} aria-hidden="true" />;
    }
    return (
      <span className={styles["table__sort-icon"]} aria-hidden="true">
        {sort.direction === "asc" ? "▲" : "▼"}
      </span>
    );
  };

  const handleRowKeyDown = (e: React.KeyboardEvent, item: T) => {
    if (onRowClick && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onRowClick(item);
    }
  };

  return (
    <div className={classNames(styles["table__wrapper"], className)}>
      {isLoadingOverlay && (
        <div className={styles["table__overlay"]}>
          <LoadingSpinner size="small" />
        </div>
      )}
      <table className={styles.table} {...(ariaLabel ? { role: "grid", "aria-label": ariaLabel } : {})}>
        <thead
          className={classNames({
            [styles["table__head--sticky"]]: stickyHeader,
          })}
        >
          <tr>
            {columns.map((column, columnIndex) => (
              <th
                key={`${columnIndex}-${String(column.key)}`}
                style={{
                  width: column.width,
                  textAlign: column.align,
                }}
                className={classNames({
                  [styles["table__header--sortable"]]: column.sortable,
                  [styles["table__header--sorted"]]: column.sortable && sort?.key === String(column.key),
                })}
                onClick={() => handleHeaderClick(column)}
                aria-sort={
                  column.sortable && sort?.key === String(column.key)
                    ? sort.direction === "asc"
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                {column.header}
                {renderSortIcon(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={columns.length} className={styles["table__loading"]}>
                {loadingContent || <LoadingSpinner size="small" text="Loading..." />}
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className={styles["table__empty-cell"]}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((item, index) => (
              <tr
                key={keyExtractor(item, index)}
                onClick={() => onRowClick?.(item)}
                onKeyDown={(e) => handleRowKeyDown(e, item)}
                className={classNames({
                  [styles["table__row--clickable"]]: !!onRowClick,
                  [styles["table__row--selected"]]: isRowSelected?.(item),
                })}
                tabIndex={onRowClick ? 0 : undefined}
              >
                {columns.map((column, columnIndex) => (
                  <td key={`${columnIndex}-${String(column.key)}`} style={{ textAlign: column.align }}>
                    {getCellValue(item, column)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default Table;
