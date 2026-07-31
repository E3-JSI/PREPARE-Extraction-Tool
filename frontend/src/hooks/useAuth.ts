import { useState, useEffect, useCallback, createContext, useContext } from "react";
import type { User, UserRegister } from "@/types";
import {
  login as apiLogin,
  register as apiRegister,
  logout as apiLogout,
  getCurrentUser,
  setToken,
  setRefreshToken,
  clearToken,
  getToken,
} from "@/api";

// ================================================
// Auth Context
// ================================================

export interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (data: UserRegister) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextType | null>(null);

// Message thrown by the API client (src/api/client.ts) when a 401 occurs and the
// refresh token is also invalid — i.e. the only signal of a genuine logged-out state.
const SESSION_EXPIRED_MESSAGE = "Session expired. Please log in again.";

// ================================================
// Auth Hook
// ================================================

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

// ================================================
// Auth Provider Hook (for creating context value)
// ================================================

export function useAuthProvider(): AuthContextType {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = !!user;

  // Check for existing token on mount
  useEffect(() => {
    // Guard against setState after unmount / cancelled run
    let active = true;

    const checkAuth = async () => {
      const token = getToken();
      if (token) {
        try {
          const userData = await getCurrentUser();
          if (active) {
            setUser(userData);
          }
        } catch (error) {
          // Only treat a real 401 (refresh failed → session expired) as logged-out.
          // The API client auto-refreshes on 401 and throws SESSION_EXPIRED_MESSAGE
          // only when the refresh token is also invalid. Transient errors
          // (network/5xx) must NOT wipe a still-valid session.
          if (error instanceof Error && error.message === SESSION_EXPIRED_MESSAGE) {
            clearToken();
          } else {
            // Keep tokens intact; surface the error for diagnostics.
            console.error("Failed to verify existing session:", error);
          }
        }
      }
      if (active) {
        setIsLoading(false);
      }
    };

    checkAuth();

    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const tokenData = await apiLogin(username, password);
    setToken(tokenData.access_token);
    setRefreshToken(tokenData.refresh_token);
    const userData = await getCurrentUser();
    setUser(userData);
  }, []);

  const register = useCallback(
    async (data: UserRegister) => {
      await apiRegister(data);
      // After successful registration, log the user in
      await login(data.username, data.password);
    },
    [login]
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      // Always tear down client-side auth state, even if the server logout call
      // fails — otherwise a thrown error would leave the UI "logged in".
      setUser(null);
    }
  }, []);

  return {
    user,
    isLoading,
    isAuthenticated,
    login,
    register,
    logout,
  };
}
