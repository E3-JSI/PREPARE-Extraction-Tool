import { useEffect, useState } from "react";

interface Props {
  datasetId: number | null;
  datasetStats: any;
  onChange: (selectedLabels: string[]) => void; // 👈 renamed (important)
}

const LabelSelector = ({ datasetStats, onChange }: Props) => {
  const [selectedLabels, setSelectedLabels] = useState<string[]>([]);

  // default select all labels when dataset changes
  useEffect(() => {
    if (!datasetStats?.labelDistribution) return;

    const allLabels = Object.keys(datasetStats.labelDistribution);
    setSelectedLabels(allLabels);
    onChange(allLabels); // immediately notify parent
  }, [datasetStats]);

  const toggleLabel = (label: string) => {
    setSelectedLabels((prev) => {
      const updated = prev.includes(label)
        ? prev.filter((l) => l !== label)
        : [...prev, label];

      onChange(updated); // 👈 instant update to parent

      return updated;
    });
  };

  if (!datasetStats?.labelDistribution) return null;

  return (
    <div style={{ marginTop: 20 }}>
      <h2>Select labels for training</h2>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {Object.keys(datasetStats.labelDistribution).map((label) => {
          const active = selectedLabels.includes(label);

          return (
            <div
              key={label}
              onClick={() => toggleLabel(label)}
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                cursor: "pointer",
                border: "1px solid #ccc",
                background: active ? "#4caf50" : "#fff",
                color: active ? "#fff" : "#000",
                userSelect: "none",
              }}
            >
              {label} ({datasetStats.labelDistribution[label]})
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default LabelSelector;