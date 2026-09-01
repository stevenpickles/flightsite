export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "flightsite-ui-theme";

const DEFAULT_THEME: Theme = "dark";

function isTheme(value: unknown): value is Theme {
  return value === "dark" || value === "light";
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

/** Applies the theme to the document root so Tailwind's `.dark` variant and
 * the native color-scheme both reflect the active theme. */
export function applyThemeClass(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}
