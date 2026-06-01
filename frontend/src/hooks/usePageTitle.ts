import { useEffect } from "react";

/**
 * Custom hook to set the page title
 * @param pageTitle - The page title (will be formatted as "{pageTitle} | PREPARE Extraction Tool")
 */
export function usePageTitle(pageTitle: string) {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${pageTitle} | PREPARE Extraction Tool`;

    // Cleanup: restore previous title on unmount
    return () => {
      document.title = previousTitle;
    };
  }, [pageTitle]);
}
