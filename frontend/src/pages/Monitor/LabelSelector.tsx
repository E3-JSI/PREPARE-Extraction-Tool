import { useEffect, useRef, useState } from "react";
import classNames from "classnames";

import type { MonitorDatasetStats } from "types";

import styles from "./styles.module.css";

interface Props {
  datasetStats: MonitorDatasetStats | null;
  onChange: (selectedLabels: string[]) => void;
}

const sameLabelSet = (a: string[], b: string[]) => {
  if (a.length !== b.length) return false;
  const setB = new Set(b);
  return a.every((label) => setB.has(label));
};

const LabelSelector = ({ datasetStats, onChange }: Props) => {
  const [selectedLabels, setSelectedLabels] = useState<string[]>([]);
  const prevLabelsRef = useRef<string[]>([]);

  // default select all labels when dataset changes
  useEffect(() => {
    if (!datasetStats?.labelDistribution) return;

    const allLabels = Object.keys(datasetStats.labelDistribution);
    setSelectedLabels(allLabels);

    // only notify the parent when the label set actually changes
    if (!sameLabelSet(prevLabelsRef.current, allLabels)) {
      prevLabelsRef.current = allLabels;
      onChange(allLabels);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetStats]);

  const toggleLabel = (label: string) => {
    setSelectedLabels((prev) => {
      const updated = prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label];

      prevLabelsRef.current = updated;
      onChange(updated); // instant update to parent

      return updated;
    });
  };

  if (!datasetStats?.labelDistribution) return null;

  // The total distribution is the source of the label list (it contains every
  // label in the dataset); reviewed counts default to 0 for labels that only
  // appear in not-yet-reviewed records.
  const reviewedDist = datasetStats.reviewedLabelDistribution ?? {};

  return (
    <div className={styles["label-selector"]}>
      <h3 className={styles["label-selector__title"]}>Select labels for training</h3>

      <div className={styles["label-selector__list"]}>
        {Object.keys(datasetStats.labelDistribution).map((label) => {
          const active = selectedLabels.includes(label);

          return (
            <button
              key={label}
              type="button"
              onClick={() => toggleLabel(label)}
              className={classNames(styles["label-toggle"], {
                [styles["label-toggle--active"]]: active,
              })}
            >
              {label} — {reviewedDist[label] ?? 0} / {datasetStats.labelDistribution[label]}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default LabelSelector;
