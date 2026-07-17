import { useState, useCallback, useRef, createContext, useContext } from "react";
import type { ToastType } from "@components/Toast";

interface ToastState {
  message: string;
  type: ToastType;
  id: number;
}

interface UseToastReturn {
  toasts: ToastState[];
  showToast: (message: string, type?: ToastType) => void;
  dismissToast: (id: number) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
  info: (message: string) => void;
}

/**
 * The imperative slice of the toast API, exposed through `ToastApiContext`.
 * Every field is a stable callback, so the object is safe to reference from
 * effect dependency arrays and context values without triggering rerenders.
 */
export interface ToastApi {
  showToast: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
  info: (message: string) => void;
}

export const ToastApiContext = createContext<ToastApi | null>(null);

/** Access the stable toast API. Must be used within a `ToastProvider`. */
export function useToastApi(): ToastApi {
  const ctx = useContext(ToastApiContext);
  if (!ctx) {
    throw new Error("useToastApi must be used within a ToastProvider");
  }
  return ctx;
}

export function useToast(): UseToastReturn {
  const toastIdRef = useRef(0);
  const [toasts, setToasts] = useState<ToastState[]>([]);

  const showToast = useCallback((message: string, type: ToastType = "info") => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { message, type, id }]);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const success = useCallback((message: string) => showToast(message, "success"), [showToast]);
  const error = useCallback((message: string) => showToast(message, "error"), [showToast]);
  const warning = useCallback((message: string) => showToast(message, "warning"), [showToast]);
  const info = useCallback((message: string) => showToast(message, "info"), [showToast]);

  return {
    toasts,
    showToast,
    dismissToast,
    success,
    error,
    warning,
    info,
  };
}
