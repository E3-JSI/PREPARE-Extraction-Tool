import React from "react";
import classNames from "classnames";

import ToolLogo from "@assets/images/logo.svg?react";

import styles from "./styles.module.css";

export interface LogoProps {
  size?: "small" | "medium" | "large";
  className?: string;
}

const Logo: React.FC<LogoProps> = ({ size = "medium", className }) => {
  return (
    <div className={classNames(styles.logo, styles[`logo--${size}`], className)}>
      <ToolLogo />
    </div>
  );
};

export default Logo;
