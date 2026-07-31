/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: "mock" | "real";
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_MOCK_SCENARIO?:
    | "normal"
    | "empty"
    | "unauthorized"
    | "validation"
    | "conflict"
    | "server-error"
    | "recommendation-failure"
    | "refresh-failure"
    | "idempotency-conflict";
  readonly VITE_MOCK_AUTH?: "anonymous" | "authenticated";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
