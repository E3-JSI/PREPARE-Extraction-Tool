import Layout from "@components/Layout";
import { usePageTitle } from "@hooks/usePageTitle";

import { useMonitor } from "./hooks/useMonitor";
import MonitorHeader from "./components/MonitorHeader";
import ViewTabs from "./components/ViewTabs";
import ModelsView from "./views/ModelsView";
import TrainingView from "./views/TrainingView";
import styles from "./styles.module.css";

/** Page body — consumes the shared Monitor state and renders the active view. */
const MonitorContent = () => {
  const { activeView } = useMonitor();

  return (
    <div className={styles.page}>
      <MonitorHeader />

      <ViewTabs />

      {activeView === "models" ? <ModelsView /> : <TrainingView />}
    </div>
  );
};

const Monitor = () => {
  usePageTitle("Monitoring");

  return (
    <Layout>
      <MonitorContent />
    </Layout>
  );
};

export default Monitor;
