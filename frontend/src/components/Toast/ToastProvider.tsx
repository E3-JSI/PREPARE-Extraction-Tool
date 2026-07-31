import { useMemo } from "react";
import type { ReactNode } from "react";

import { useToast, ToastApiContext } from "@hooks/useToast";
import type { ToastApi } from "@hooks/useToast";

import ToastContainer from "./ToastContainer";

interface ToastProviderProps {
  children: ReactNode;
  /** Auto-dismiss delay per toast, in ms. */
  duration?: number;
}

/**
 * Hosts toast state and renders the `ToastContainer` itself, exposing only the
 * stable imperative API (`useToastApi`) through context. Showing or dismissing
 * a toast therefore rerenders just this provider and the container — never the
 * `children` subtree (its element identity and the context value both stay
 * stable across toast changes).
 */
const ToastProvider = ({ children, duration = 5000 }: ToastProviderProps) => {
  const { toasts, showToast, dismissToast, success, error, warning, info } = useToast();

  // All fields are stable useCallbacks, so this memoizes to a constant object.
  const api = useMemo<ToastApi>(
    () => ({ showToast, success, error, warning, info }),
    [showToast, success, error, warning, info]
  );

  return (
    <ToastApiContext.Provider value={api}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} duration={duration} />
    </ToastApiContext.Provider>
  );
};

export default ToastProvider;
