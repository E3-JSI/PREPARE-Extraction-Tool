import React, { useState } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import classNames from "classnames";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGripVertical, faPencil, faCheck, faXmark } from "@fortawesome/free-solid-svg-icons";

import Button from "@components/Button";
import DraggableTerm from "@components/DraggableTerm";
import { getLabelColorClass } from "@/utils/labelColors";
import type { ClusterData } from "@/types";

import styles from "./styles.module.css";

interface ClusterCardProps {
  cluster: ClusterData;
  labels: string[];
  onRename: (newTitle: string) => void;
  onDelete: () => void;
  onRemoveTerm: (termId: number) => void;
  isDraggingCluster: boolean;
  readOnly?: boolean;
}

const ClusterCard: React.FC<ClusterCardProps> = ({
  cluster,
  labels,
  onRename,
  onDelete,
  onRemoveTerm,
  isDraggingCluster,
  readOnly = false,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(cluster.title);

  const {
    attributes: dragAttributes,
    listeners: dragListeners,
    setNodeRef: setDragRef,
    isDragging,
  } = useDraggable({
    id: `drag-cluster-${cluster.id}`,
    data: { type: "cluster", clusterId: cluster.id, cluster },
    disabled: readOnly,
  });

  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `cluster-${cluster.id}`,
    data: { clusterId: cluster.id },
    disabled: readOnly,
  });

  const setNodeRef = (node: HTMLElement | null) => {
    setDragRef(node);
    setDropRef(node);
  };

  const handleRename = () => {
    if (editTitle.trim() && editTitle !== cluster.title) {
      onRename(editTitle.trim());
    }
    setIsEditing(false);
  };

  const labelStyle = cluster.label_color
    ? {
        backgroundColor: `${cluster.label_color}20`,
        color: cluster.label_color,
        border: `1px solid ${cluster.label_color}40`,
      }
    : {};

  const labelColorClass = cluster.label_color ? "custom-label" : getLabelColorClass(cluster.label, labels);

  return (
    <div
      ref={setNodeRef}
      className={classNames(styles["cluster-card"], {
        [styles["cluster-card--merge-target"]]: isOver && isDraggingCluster,
        [styles["cluster-card--drag-over"]]: isOver && !isDraggingCluster,
        [styles["cluster-card--dragging"]]: isDragging,
      })}
      data-cluster-id={cluster.id}
    >
      <div className={styles["cluster-card__header"]}>
        {!readOnly && (
          <div
            className={styles["cluster-card__drag-handle"]}
            {...dragListeners}
            {...dragAttributes}
            title="Drag to merge with another cluster"
          >
            <FontAwesomeIcon icon={faGripVertical} />
          </div>
        )}

        <div className={styles["cluster-card__name"]}>
          {isEditing && !readOnly ? (
            <div className={styles["cluster-card__name-edit"]}>
              <input
                type="text"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleRename();
                  if (e.key === "Escape") {
                    setEditTitle(cluster.title);
                    setIsEditing(false);
                  }
                }}
                autoFocus
                className={styles["cluster-card__title-input"]}
              />
              <Button
                variant="ghost"
                size="icon"
                onClick={handleRename}
                className={styles["cluster-card__btn-edit-action"]}
                title="Save"
              >
                <FontAwesomeIcon icon={faCheck} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  setEditTitle(cluster.title);
                  setIsEditing(false);
                }}
                className={classNames(styles["cluster-card__btn-edit-action"], styles["cluster-card__btn-edit-cancel"])}
                title="Cancel"
              >
                <FontAwesomeIcon icon={faXmark} />
              </Button>
            </div>
          ) : (
            <div className={styles["cluster-card__name-display"]}>
              <h3>{cluster.title}</h3>
              {!readOnly && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => {
                    setEditTitle(cluster.title);
                    setIsEditing(true);
                  }}
                  className={styles["cluster-card__btn-edit-name"]}
                  title="Edit cluster name"
                >
                  <FontAwesomeIcon icon={faPencil} />
                </Button>
              )}
            </div>
          )}
        </div>

        <div className={styles["cluster-card__stats"]}>
          <span title="Total terms">{cluster.total_terms} terms</span>
          <span title="Total occurrences">{cluster.total_occurrences} occurrences</span>
          <span title="Unique records">{cluster.unique_records} unique records</span>
        </div>

        <span
          className={classNames(styles["cluster-card__label-badge"], styles[labelColorClass])}
          style={labelStyle}
        >
          {cluster.label}
        </span>

        {!readOnly && (
          <div className={styles["cluster-card__header-actions"]}>
            <Button variant="outline" size="small" colorScheme="danger" onClick={onDelete}>
              Delete
            </Button>
          </div>
        )}
      </div>

      <div className={styles["cluster-card__body"]}>
        <div className={styles["cluster-card__terms-list"]}>
          {cluster.terms.map((term) => (
            <DraggableTerm
              key={term.term_id}
              term={term}
              clusterId={cluster.id}
              onRemove={onRemoveTerm}
              readOnly={readOnly}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

export default ClusterCard;
