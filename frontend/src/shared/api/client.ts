import type { AccessTokenResponse, ApiErrorBody } from "./types";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

let accessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;
let authFailureHandler: (() => void) | null = null;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
    this.requestId = body.request_id ?? null;
  }
}

export interface RequestOptions extends Omit<RequestInit, "body" | "headers"> {
  body?: unknown;
  headers?: HeadersInit;
  idempotencyKey?: string;
  skipAuthRefresh?: boolean;
  skipAuthFailure?: boolean;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAuthFailureHandler(handler: (() => void) | null): void {
  authFailureHandler = handler;
}

function toUrl(path: string): string {
  return `${apiBaseUrl}${path}`;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { message: text };
  }
}

function toApiError(status: number, payload: unknown): ApiError {
  const body = (payload && typeof payload === "object" ? payload : {}) as Partial<ApiErrorBody>;
  return new ApiError(status, {
    code: body.code ?? "INTERNAL_ERROR",
    message: body.message ?? "服务暂时不可用，请稍后重试。",
    details: body.details,
    request_id: body.request_id,
  });
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;

  refreshPromise = fetch(toUrl("/api/v1/auth/refresh"), {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json" },
  })
    .then(async (response) => {
      const payload = await readBody(response);
      if (!response.ok) {
        clearAccessToken();
        return null;
      }

      const token = (payload as AccessTokenResponse).access_token;
      if (!token) {
        clearAccessToken();
        return null;
      }

      setAccessToken(token);
      return token;
    })
    .catch(() => {
      clearAccessToken();
      return null;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers: requestHeaders, idempotencyKey, skipAuthRefresh, skipAuthFailure, ...fetchOptions } = options;
  const headers = new Headers(requestHeaders);
  headers.set("Accept", "application/json");

  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  if (idempotencyKey) {
    headers.set("Idempotency-Key", idempotencyKey);
  }

  const response = await fetch(toUrl(path), {
    ...fetchOptions,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
    headers,
  });

  if (response.status === 401 && !skipAuthRefresh) {
    const token = await refreshAccessToken();
    if (token) {
      return request<T>(path, { ...options, skipAuthRefresh: true });
    }
  }

  if (response.status === 401) {
    clearAccessToken();
    if (!skipAuthFailure) authFailureHandler?.();
  }

  const payload = await readBody(response);
  if (!response.ok) {
    throw toApiError(response.status, payload);
  }

  return payload as T;
}
