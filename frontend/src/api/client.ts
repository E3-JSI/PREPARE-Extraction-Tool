// ================================================
// Configuration
// ================================================

// Use VITE_BACKEND_HOST from environment if set (production/docker),
// otherwise use relative path for development (proxied by Vite)
export const API_BASE_URL = import.meta.env.VITE_BACKEND_HOST
  ? `${import.meta.env.VITE_BACKEND_HOST}/api/v1`
  : "/api/v1";

// ================================================
// Token management
// ================================================

const TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

// Flag to prevent multiple concurrent refresh attempts
let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

/**
 * Attempts to refresh the access token using the refresh token.
 * Returns true if successful, false otherwise.
 */
async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();

  if (!refreshToken) {
    return false;
  }

  // If already refreshing, wait for the existing request
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        // Refresh token is invalid, clear all tokens
        clearToken();
        return false;
      }

      const data = await response.json();
      setToken(data.access_token);
      setRefreshToken(data.refresh_token);
      return true;
    } catch {
      clearToken();
      return false;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

// ================================================
// API client
// ================================================

/**
 * Error thrown for non-OK responses. Carries the HTTP `status` and the parsed
 * response `detail` (which may be a string or a structured object such as
 * `{ error, message, suggestion }`) so callers can branch on machine-readable
 * error codes. `message` is always a human-readable string.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface RequestOptions extends RequestInit {
  skipAuth?: boolean;
  skipRefresh?: boolean; // Used internally to prevent infinite refresh loops
}

export async function apiRequest<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { skipAuth = false, skipRefresh = false, headers: customHeaders, ...rest } = options;

  const headers: HeadersInit = {
    ...customHeaders,
  };

  // Add auth header if token exists and not skipped
  if (!skipAuth) {
    const token = getToken();
    if (token) {
      (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
    }
  }

  // Add content-type for JSON bodies
  if (rest.body && typeof rest.body === "string") {
    (headers as Record<string, string>)["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...rest,
    headers,
  });

  // Handle 401 errors - attempt token refresh
  if (response.status === 401 && !skipAuth && !skipRefresh) {
    const refreshed = await refreshAccessToken();

    if (refreshed) {
      // Retry the request with the new token
      return apiRequest<T>(endpoint, { ...options, skipRefresh: true });
    }

    // Refresh failed - throw error to trigger logout
    throw new Error("Session expired. Please log in again.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    const detail = (body as { detail?: unknown })?.detail;
    // `detail` may be a plain string or a structured object (e.g. bioner's
    // `{ error, message, suggestion }`). Derive a readable message either way.
    const message =
      typeof detail === "string"
        ? detail
        : (detail as { message?: string } | null)?.message || `HTTP ${response.status}`;
    throw new ApiError(response.status, message, detail);
  }

  // Handle empty responses
  const text = await response.text();
  if (!text) {
    return {} as T;
  }

  return JSON.parse(text) as T;
}
