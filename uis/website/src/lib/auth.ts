export const AUTH_TOKEN_KEY = "brasaland.access_token";
export const AUTH_SESSION_CLEARED_EVENT = "brasaland:auth-session-cleared";

export type AuthenticatedUser = {
  id: string;
  email: string;
  role: "admin" | "manager" | "user";
  profile: UserProfile | null;
};

export type UserProfile = {
  id: string;
  user_id: string;
  name: string | null;
  phone: string | null;
  address: string | null;
};

type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
};

type ApiErrorPayload = {
  detail?: string;
  error?: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function resolveApiBase(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_SUPPLIERS_API_URL;

  if (configuredUrl) {
    return configuredUrl.replace(/\/suppliers\/?$/, "").replace(/\/$/, "");
  }

  return "/api";
}

export const API_BASE = resolveApiBase();

export function getStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function storeToken(token: string): void {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
    window.dispatchEvent(new Event(AUTH_SESSION_CLEARED_EVENT));
  }
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as ApiErrorPayload;
    return payload.detail ?? payload.error ?? `La API respondió con HTTP ${response.status}.`;
  } catch {
    return `La API respondió con HTTP ${response.status}.`;
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("No se pudo conectar con la API. Comprueba que el servicio esté disponible.", 0);
  }

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
  }

  return (await response.json()) as T;
}

export async function authenticatedApiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  if (!token) {
    throw new ApiError("Tu sesión ha caducado. Vuelve a iniciar sesión.", 401);
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);

  try {
    return await apiFetch<T>(path, { ...init, headers });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      clearToken();
    }
    throw error;
  }
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const token = await apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  storeToken(token.access_token);
  return token;
}

export async function registerAndLogin(payload: {
  email: string;
  password: string;
  name?: string;
}): Promise<TokenResponse> {
  await apiFetch("/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  return login(payload.email, payload.password);
}

export async function getCurrentUser(): Promise<AuthenticatedUser> {
  return authenticatedApiFetch<AuthenticatedUser>("/auth/me");
}

export async function updateCurrentUserProfile(
  payload: Pick<UserProfile, "name" | "phone" | "address">,
): Promise<UserProfile> {
  return authenticatedApiFetch<UserProfile>("/profiles/me", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function requestPasswordReset(email: string): Promise<void> {
  await apiFetch("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await apiFetch("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await authenticatedApiFetch("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}
