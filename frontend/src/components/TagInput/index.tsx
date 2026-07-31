import { useState, useRef, useCallback } from "react";
import classNames from "classnames";
import styles from "./styles.module.css";

interface TagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
}

const TagInput: React.FC<TagInputProps> = ({
  tags,
  onChange,
  placeholder = "Type and press Enter",
  disabled = false,
  id,
  className,
}) => {
  const [inputValue, setInputValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addTags = useCallback(
    (raw: string) => {
      const seen = new Set(tags);
      const newTags: string[] = [];
      for (const t of raw.split(",").map((t) => t.trim())) {
        if (t !== "" && !seen.has(t)) {
          seen.add(t);
          newTags.push(t);
        }
      }
      if (newTags.length > 0) {
        onChange([...tags, ...newTags]);
      }
    },
    [tags, onChange]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      if (inputValue.trim()) {
        addTags(inputValue);
        setInputValue("");
      }
    } else if (e.key === "Backspace" && inputValue === "" && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text");
    addTags(pasted);
    setInputValue("");
  };

  const handleBlur = () => {
    setIsFocused(false);
    if (inputValue.trim()) {
      addTags(inputValue);
      setInputValue("");
    }
  };

  const removeTag = (index: number) => {
    onChange(tags.filter((_, i) => i !== index));
  };

  const handleContainerClick = () => {
    inputRef.current?.focus();
  };

  return (
    <div
      className={classNames(styles["tag-input"], className, {
        [styles["tag-input--focused"]]: isFocused,
        [styles["tag-input--disabled"]]: disabled,
      })}
      onClick={handleContainerClick}
    >
      {tags.map((tag, index) => (
        <span key={`${index}-${tag}`} className={styles["tag-input__tag"]}>
          {tag}
          <button
            type="button"
            className={styles["tag-input__tag-remove"]}
            onClick={(e) => {
              e.stopPropagation();
              removeTag(index);
            }}
            disabled={disabled}
            aria-label={`Remove ${tag}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        id={id}
        type="text"
        className={styles["tag-input__input"]}
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onFocus={() => setIsFocused(true)}
        onBlur={handleBlur}
        placeholder={tags.length === 0 ? placeholder : ""}
        disabled={disabled}
      />
    </div>
  );
};

export default TagInput;
