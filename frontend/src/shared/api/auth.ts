import { clearAccessToken, request, setAccessToken } from "./client";
import type {
  AccessTokenResponse,
  AuthUserView,
  CredentialsRequest,
  LoginResponse,
} from "./types";

let restorePromise: Promise<AuthUserView> | null = null;

export const authApi = {
  async login(input: CredentialsRequest): Promise<LoginResponse> {
    const response = await request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: input,
      skipAuthRefresh: true,
      skipAuthFailure: true,
    });
    setAccessToken(response.access_token);
    return response;
  },

  async register(input: CredentialsRequest): Promise<LoginResponse> {
    const response = await request<LoginResponse>("/api/v1/auth/register", {
      method: "POST",
      body: input,
      skipAuthRefresh: true,
      skipAuthFailure: true,
    });
    setAccessToken(response.access_token);
    return response;
  },

  async restore(): Promise<AuthUserView> {
    if (restorePromise) return restorePromise;

    restorePromise = request<AccessTokenResponse>("/api/v1/auth/refresh", {
      method: "POST",
      skipAuthRefresh: true,
      skipAuthFailure: true,
    })
      .then((token) => {
        setAccessToken(token.access_token);
        return request<AuthUserView>("/api/v1/auth/me");
      })
      .finally(() => {
        restorePromise = null;
      });

    return restorePromise;
  },

  async me(): Promise<AuthUserView> {
    return request<AuthUserView>("/api/v1/auth/me");
  },

  async logout(): Promise<void> {
    try {
      await request<void>("/api/v1/auth/logout", {
        method: "POST",
        skipAuthRefresh: true,
        skipAuthFailure: true,
      });
    } finally {
      clearAccessToken();
    }
  },
};
