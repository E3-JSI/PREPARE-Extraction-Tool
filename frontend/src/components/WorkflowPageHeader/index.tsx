import React from "react";
import { useNavigate } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleQuestion, faArrowLeft, faArrowRight, faFolderBlank } from "@fortawesome/free-solid-svg-icons";

import Button from "@components/Button";

import styles from "./styles.module.css";

interface NavButton {
  label: string;
  to: string;
  title?: string;
}

interface WorkflowPageHeaderProps {
  title: string;
  datasetId?: string;
  datasetName?: string;
  subtitle?: string;
  backButton: NavButton;
  forwardButton?: NavButton;
  helpContent?: React.ReactNode;
}

const WorkflowPageHeader: React.FC<WorkflowPageHeaderProps> = ({
  title,
  datasetId,
  datasetName,
  subtitle,
  backButton,
  forwardButton,
  helpContent,
}) => {
  const navigate = useNavigate();

  return (
    <div className={styles["header"]}>
      <Button variant="outline" onClick={() => navigate(backButton.to)} title={backButton.title}>
        <FontAwesomeIcon icon={faArrowLeft} /> {backButton.label}
      </Button>

      <div className={styles["header__info"]}>
        <h1 className={styles["header__title"]}>
          {title}
          {helpContent && (
            <span className={styles["info-tooltip"]}>
              <FontAwesomeIcon icon={faCircleQuestion} className={styles["info-tooltip__icon"]} />
              <span className={styles["info-tooltip__content"]}>{helpContent}</span>
            </span>
          )}
        </h1>
        {datasetId && (
          <Button
            variant="outline"
            className={styles["header__dataset-link"]}
            onClick={() => navigate(`/datasets/${datasetId}`)}
            title="Go to Dataset Overview"
          >
            <FontAwesomeIcon icon={faFolderBlank} /> {datasetName || "Loading..."}
          </Button>
        )}
        {!datasetId && subtitle && <p className={styles["header__subtitle"]}>{subtitle}</p>}
      </div>

      {forwardButton && (
        <Button variant="outline" onClick={() => navigate(forwardButton.to)} title={forwardButton.title}>
          {forwardButton.label} <FontAwesomeIcon icon={faArrowRight} />
        </Button>
      )}
    </div>
  );
};

export default WorkflowPageHeader;
