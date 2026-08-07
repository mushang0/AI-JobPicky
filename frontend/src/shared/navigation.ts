const SCROLL_KEY_PREFIX = "jobpicky:scroll:";

export function currentPath(pathname: string, search: string): string {
  return `${pathname}${search}`;
}

export function jobDetailPath(jobId: string, returnTo?: string): string {
  const path = `/jobs/${encodeURIComponent(jobId)}`;
  return returnTo ? `${path}?returnTo=${encodeURIComponent(returnTo)}` : path;
}

export function safeInternalPath(value: string | null | undefined, fallback = "/jobs"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return fallback;
  return value;
}

export function saveListScroll(path: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(`${SCROLL_KEY_PREFIX}${path}`, String(Math.round(window.scrollY)));
  } catch {
    // Storage can be unavailable in private browsing; browser history still works.
  }
}

export function restoreListScroll(path: string): void {
  if (typeof window === "undefined") return;
  try {
    const value = window.sessionStorage.getItem(`${SCROLL_KEY_PREFIX}${path}`);
    if (value === null) return;
    window.sessionStorage.removeItem(`${SCROLL_KEY_PREFIX}${path}`);
    const scrollY = Number(value);
    if (!Number.isFinite(scrollY)) return;
    window.requestAnimationFrame(() => window.scrollTo({ top: scrollY, behavior: "auto" }));
  } catch {
    // Storage can be unavailable in private browsing; browser history still works.
  }
}
