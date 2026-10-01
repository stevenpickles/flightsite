/**
 * The stored theme preference vs. the resolved dark/light value actually
 * applied to the document (roadmap slice 082).
 *
 * `Theme` is what the user chose and what persists: `"dark"`, `"light"`, or
 * `"system"` (follow the OS). `ResolvedTheme` is always one of the two real
 * appearances — `"system"` is never a class on `<html>`, only ever resolved
 * to one via {@link resolveTheme} first. Every consumer that needs an actual
 * dark/light answer (the basemap's theme affinity, ECharts' color tokens)
 * reads the resolved value, never `theme` directly — see
 * `useActiveBasemap.ts` and `chartTheme.ts`.
 *
 * Backward compatibility (roadmap slice 082's contract): a stored `"dark"`
 * or `"light"` from before this slice reads back exactly as it did — the
 * default for anyone with nothing stored, or a corrupted value, stays
 * `"dark"`, not `"system"`. Only a user who explicitly picks System through
 * {@link ThemeToggle} ever stores that value.
 */

export type Theme = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

export const THEME_STORAGE_KEY = "flightsite-ui-theme";

const DEFAULT_THEME: Theme = "dark";

const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

function isTheme(value: unknown): value is Theme {
  return value === "dark" || value === "light" || value === "system";
}

/** Reads the persisted theme preference. Falls back to the dark default on
 * any error (private browsing, disabled storage, corrupted value, etc.). */
export function readStoredTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

/** Persists the theme preference. Silently no-ops if storage is unavailable. */
export function writeStoredTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage unavailable (private browsing, quota, disabled) — theme still
    // applies for this session via in-memory state.
  }
}

/**
 * The OS's current dark/light preference, read once. Falls back to `true`
 * (dark) wherever `matchMedia` is unavailable — there is no SSR in this app,
 * so in practice that only covers a test environment that has not stubbed
 * it, which is also the app's own default (`DEFAULT_THEME`).
 */
export function readSystemPrefersDark(): boolean {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return true;
  }
  try {
    return window.matchMedia(SYSTEM_DARK_QUERY).matches;
  } catch {
    return true;
  }
}

/**
 * Subscribes to live changes in the OS's dark/light preference — the
 * mechanism that lets a "System" theme follow `prefers-color-scheme`
 * without a reload. Returns an unsubscribe function; a no-op subscription
 * wherever `matchMedia` is unavailable, mirroring
 * `components/shell/useIsMobile.ts`'s own fallback.
 */
export function watchSystemPrefersDark(
  onChange: (prefersDark: boolean) => void,
): () => void {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return () => {};
  }
  const mql = window.matchMedia(SYSTEM_DARK_QUERY);
  const listener = (event: MediaQueryListEvent) => {
    onChange(event.matches);
  };
  mql.addEventListener("change", listener);
  return () => {
    mql.removeEventListener("change", listener);
  };
}

/** Resolves a stored preference to the dark/light value that is actually
 * applied — `"system"` deferring to the live OS reading the caller already
 * has (from {@link readSystemPrefersDark} or a subsequent
 * {@link watchSystemPrefersDark} callback). */
export function resolveTheme(
  theme: Theme,
  systemPrefersDark: boolean,
): ResolvedTheme {
  return theme === "system" ? (systemPrefersDark ? "dark" : "light") : theme;
}

/** Applies a *resolved* theme to the document root so Tailwind's `.dark`
 * variant and the native color-scheme both reflect it. Takes
 * {@link ResolvedTheme}, never the raw {@link Theme} — a caller holding
 * `"system"` must resolve it first (see {@link resolveTheme}). */
export function applyThemeClass(theme: ResolvedTheme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}
