import { NavLink, useNavigate } from "react-router-dom";
import classNames from "classnames";

import UserAvatar from "@components/UserAvatar";
import Dropdown from "@components/Dropdown";
import Logo from "@components/Logo";

import { useAuth } from "@/hooks/useAuth";

import styles from "./styles.module.css";

const Header = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const dropdownItems = [
    {
      label: "View Profile",
      onClick: () => navigate("/profile"),
    },
    {
      label: "Logout",
      onClick: logout,
      variant: "danger" as const,
    },
  ];

  return (
    <header className={styles.header}>
      <div className={styles["header__left"]}>
        <Logo size="small" />
      </div>

      <nav className={styles["header__nav"]}>
        <NavLink
          to="/datasets"
          className={({ isActive }) =>
            classNames(styles["header__nav-link"], {
              [styles["header__nav-link--active"]]: isActive,
            })
          }
        >
          Datasets
        </NavLink>
        <NavLink
          to="/vocabularies"
          className={({ isActive }) =>
            classNames(styles["header__nav-link"], {
              [styles["header__nav-link--active"]]: isActive,
            })
          }
        >
          Vocabularies
        </NavLink>
        <NavLink
          to="/monitor"
          className={({ isActive }) =>
            classNames(styles["header__nav-link"], {
              [styles["header__nav-link--active"]]: isActive,
            })
          }
        >
          Monitor
        </NavLink>
        <NavLink
          to="/model_settings"
          className={({ isActive }) =>
            classNames(styles["header__nav-link"], {
              [styles["header__nav-link--active"]]: isActive,
            })
          }
        >
          Settings
        </NavLink>
      </nav>

      <div className={styles["header__right"]}>
        {user && (
          <Dropdown
            trigger={<UserAvatar username={user.username} size="medium" />}
            items={dropdownItems}
            align="right"
          />
        )}
      </div>
    </header>
  );
};

export default Header;
