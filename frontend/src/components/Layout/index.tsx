import Header from "@components/Header";

import styles from "./styles.module.css";

export interface LayoutProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode;
}

const Layout = ({ children, sidebar }: LayoutProps) => {
  return (
    <div className={styles.layout}>
      <Header />
      <div className={styles["layout__container"]}>
        {sidebar && <aside className={styles["layout__sidebar"]}>{sidebar}</aside>}
        <main className={styles["layout__main"]}>{children}</main>
      </div>
      <footer className={styles["layout__footer"]}>
        <span>&copy; 2023-2027 PREPARE Project.</span>
      </footer>
    </div>
  );
};

export default Layout;
