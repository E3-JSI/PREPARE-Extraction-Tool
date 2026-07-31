import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleQuestion } from "@fortawesome/free-solid-svg-icons";

import styles from "./styles.module.css";

/**
 * Standalone page header for the Monitor page. Matches the style of the
 * workflow page headers (title + info tooltip) but omits the back/forward
 * workflow navigation, since Monitor is not part of the linear workflow.
 */
const MonitorHeader = () => {
  return (
    <header className={styles.header}>
      <h1 className={styles.title}>
        Monitoring Dashboard
        <span className={styles["info-tooltip"]}>
          <FontAwesomeIcon icon={faCircleQuestion} className={styles["info-tooltip__icon"]} />
          <span className={styles["info-tooltip__content"]}>
            <strong>Monitoring Dashboard</strong>
            <p>Train custom NER models and pick which one is used for extraction. Switch between:</p>
            <ul>
              <li>
                <strong>Models</strong> — browse trained models, inspect each one's training loss and per-label
                evaluation, and select the global model used for extraction.
              </li>
              <li>
                <strong>Training</strong> — choose training datasets and labels, configure the base model and
                hyperparameters, then launch a run and follow its live loss and evaluation curves.
              </li>
            </ul>
          </span>
        </span>
      </h1>
      <p className={styles.subtitle}>Train NER models, follow live training metrics, and compare run performance.</p>
    </header>
  );
};

export default MonitorHeader;
