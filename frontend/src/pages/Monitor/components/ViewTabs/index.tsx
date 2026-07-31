import classNames from "classnames";

import { useMonitor } from "../../hooks/useMonitor";
import type { MonitorView } from "../../hooks/useMonitor";
import styles from "./styles.module.css";

const TABS: { id: MonitorView; label: string }[] = [
  { id: "models", label: "Models" },
  { id: "training", label: "Training" },
];

/** Top-level toggle between the Comparison and Training views. */
const ViewTabs = () => {
  const { activeView, setActiveView } = useMonitor();

  return (
    <div className={styles.tabs} role="tablist" aria-label="Monitor views">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeView === tab.id}
          className={classNames(styles.tab, {
            [styles["tab--active"]]: activeView === tab.id,
          })}
          onClick={() => setActiveView(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
};

export default ViewTabs;
