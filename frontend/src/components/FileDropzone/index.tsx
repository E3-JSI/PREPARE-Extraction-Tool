import { useCallback, useState, useRef } from "react";
import classNames from "classnames";

import Button from "@components/Button";

import styles from "./styles.module.css";

export interface FileDropzoneProps {
  onFileSelect: (file: File) => void;
  accept?: string;
  maxSize?: number; // in bytes
  disabled?: boolean;
}

const FileDropzone = ({
  onFileSelect,
  accept = ".csv,.json",
  maxSize = 2 * 1024 * 1024 * 1024, // 2GB default
  disabled = false,
}: FileDropzoneProps) => {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const validateFile = useCallback(
    (file: File): string | null => {
      if (file.size > maxSize) {
        return `File size exceeds ${Math.round(maxSize / 1024 / 1024)}MB limit`;
      }

      if (accept) {
        const acceptedTypes = accept.split(",").map((t) => t.trim().toLowerCase());
        const fileExtension = `.${file.name.split(".").pop()?.toLowerCase()}`;
        const fileType = file.type.toLowerCase();

        const isAccepted = acceptedTypes.some((type) => {
          if (type.startsWith(".")) {
            return fileExtension === type;
          }
          return fileType === type || fileType.startsWith(type.replace("*", ""));
        });

        if (!isAccepted) {
          return `File type not accepted. Allowed: ${accept}`;
        }
      }

      return null;
    },
    [accept, maxSize]
  );

  const handleFile = useCallback(
    (file: File) => {
      const validationError = validateFile(file);
      if (validationError) {
        setError(validationError);
        setSelectedFile(null);
        return;
      }

      setError(null);
      setSelectedFile(file);
      onFileSelect(file);
    },
    [validateFile, onFileSelect]
  );

  const handleDragEnter = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragDepth.current += 1;
      if (!disabled) {
        setIsDragging(true);
      }
    },
    [disabled]
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragDepth.current = 0;
      setIsDragging(false);

      if (disabled) return;

      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFile(files[0]);
      }
    },
    [disabled, handleFile]
  );

  const handleClick = useCallback(() => {
    if (!disabled) {
      fileInputRef.current?.click();
    }
  }, [disabled]);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        handleFile(files[0]);
      }
    },
    [handleFile]
  );

  const formatFileSize = (bytes: number): string => {
    if (bytes >= 1024 * 1024 * 1024) {
      return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    } else if (bytes >= 1024 * 1024) {
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    } else {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
  };

  return (
    <div
      className={classNames(styles.dropzone, {
        [styles["dropzone--dragging"]]: isDragging,
        [styles["dropzone--disabled"]]: disabled,
        [styles["dropzone--has-file"]]: selectedFile,
      })}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      onClick={handleClick}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        onChange={handleInputChange}
        className={styles["dropzone__hidden-input"]}
        disabled={disabled}
      />

      <div className={styles["dropzone__content"]}>
        <div className={styles["dropzone__icon"]}>
          <svg
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
        </div>

        {selectedFile ? (
          <div className={styles["dropzone__selected-info"]}>
            <span className={styles["dropzone__file-name"]}>{selectedFile.name}</span>
            <span className={styles["dropzone__file-size"]}>({formatFileSize(selectedFile.size)})</span>
          </div>
        ) : (
          <>
            <span className={styles["dropzone__text"]}>Drag and drop</span>
            <span className={styles["dropzone__or"]}>or</span>
            <Button variant="primary" type="button">
              Browse for file
            </Button>
          </>
        )}

        {error && <span className={styles["dropzone__error"]}>{error}</span>}
      </div>
    </div>
  );
};

export default FileDropzone;
