import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { authApi } from "../../shared/api/auth";
import { clearAccessToken, setAuthFailureHandler } from "../../shared/api/client";
import type { AuthUserView, CredentialsRequest } from "../../shared/api/types";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUserView | null;
  signIn: (input: CredentialsRequest) => Promise<void>;
  signUp: (input: CredentialsRequest) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUserView | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const returnTo = `${location.pathname}${location.search}`;
    setAuthFailureHandler(() => {
      clearAccessToken();
      setUser(null);
      setStatus("anonymous");
      if (location.pathname !== "/login" && location.pathname !== "/register") {
        navigate(`/login?returnTo=${encodeURIComponent(returnTo)}`, { replace: true });
      }
    });

    return () => setAuthFailureHandler(null);
  }, [location.pathname, location.search, navigate]);

  useEffect(() => {
    let active = true;

    authApi
      .restore()
      .then((restoredUser) => {
        if (!active) return;
        setUser(restoredUser);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        clearAccessToken();
        setUser(null);
        setStatus("anonymous");
      });

    return () => {
      active = false;
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      async signIn(input) {
        const response = await authApi.login(input);
        setUser(response.user);
        setStatus("authenticated");
      },
      async signUp(input) {
        const response = await authApi.register(input);
        setUser(response.user);
        setStatus("authenticated");
      },
      async signOut() {
        try {
          await authApi.logout();
        } finally {
          setUser(null);
          setStatus("anonymous");
        }
      },
    }),
    [status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return value;
}
