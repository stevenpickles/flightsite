import { create } from "zustand";

import {
  applyThemeClass,
  readStoredTheme,
  readSystemPrefersDark,
  resolveTheme,
  watchSystemPrefersDark,
  writeStoredTheme,
} from "@/lib/theme";
import type { ResolvedTheme, Theme } from "@/lib/theme";

/** Persisted per-browser sidebar collapse (roadmap slice 082) — same
 * guarded-localStorage shape as `lib/theme.ts`'s theme helpers: falls back
 * to the documented default (expanded) on any error or malformed value, and
 * never throws. A dedicated key rather than folding into the theme key,
 * since the two preferences are unrelated and either may outlive the
 * other. */
export const SIDEBAR_COLLAPSED_STORAGE_KEY = "flightsite-sidebar-collapsed";

function readStoredSidebarCollapsed(): boolean {
  try {
    return (
      window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true"
    );
  } catch {
    return false;
  }
}

function writeStoredSidebarCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(
      SIDEBAR_COLLAPSED_STORAGE_KEY,
      collapsed ? "true" : "false",
    );
  } catch {
    // Storage unavailable (private browsing, quota, disabled) — the choice
    // still applies for this session via in-memory state.
  }
}

/** The cycle a click on `ThemeToggle` steps through. Dark first, matching
 * the pre-082 toggle's first step, so an existing dark-default user's first
 * click still lands on Light exactly as before. */
const THEME_CYCLE: readonly Theme[] = ["dark", "light", "system"];

export interface UiState {
  /** The user's stored preference — `"system"` means "follow the OS", not a
   * resolved appearance. Read `resolvedTheme` for the latter. */
  theme: Theme;
  /** The OS's current dark/light preference, kept live by a `matchMedia`
   * change listener (roadmap slice 082) — consulted only while `theme` is
   * `"system"`, but tracked unconditionally so it is already current the
   * moment a user switches to System. */
  systemPrefersDark: boolean;
  /** Whether the primary sidebar is collapsed to icon-only width. Persisted
   * to localStorage (roadmap slice 082). */
  sidebarCollapsed: boolean;
  setTheme: (theme: Theme) => void;
  /** Cycles Dark -> Light -> System -> Dark. */
  toggleTheme: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
}

/** The resolved theme this store is currently applying — a plain function
 * rather than a stored field, so it can never drift from `theme` and
 * `systemPrefersDark`: both `setTheme` and the module-level `matchMedia`
 * listener below write those two fields directly with `set`, and every
 * reader (including this store's own actions) re-derives from them fresh. */
function currentResolvedTheme(
  state: Pick<UiState, "theme" | "systemPrefersDark">,
): ResolvedTheme {
  return resolveTheme(state.theme, state.systemPrefersDark);
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: readStoredTheme(),
  systemPrefersDark: readSystemPrefersDark(),
  sidebarCollapsed: readStoredSidebarCollapsed(),

  setTheme: (theme) => {
    writeStoredTheme(theme);
    applyThemeClass(resolveTheme(theme, get().systemPrefersDark));
    set({ theme });
  },

  toggleTheme: () => {
    const currentIndex = THEME_CYCLE.indexOf(get().theme);
    const next = THEME_CYCLE[(currentIndex + 1) % THEME_CYCLE.length];
    get().setTheme(next ?? "dark");
  },

  setSidebarCollapsed: (collapsed) => {
    writeStoredSidebarCollapsed(collapsed);
    set({ sidebarCollapsed: collapsed });
  },

  toggleSidebar: () => {
    get().setSidebarCollapsed(!get().sidebarCollapsed);
  },
}));

/** The resolved (`"dark"`/`"light"`) theme the app should render right now.
 * Every consumer that needs an actual appearance rather than the raw
 * preference reads this — `useActiveBasemap.ts` (basemap theme affinity) and
 * `EChart.tsx` (chart color tokens) — so neither has to know "system"
 * exists. */
export function useResolvedTheme(): ResolvedTheme {
  return useUiStore(currentResolvedTheme);
}

/**
 * Live system-theme following (roadmap slice 082, module-scoped so it is
 * wired exactly once per module graph): whenever the OS's dark/light
 * preference changes, records it, and — only while the user's own
 * preference is `"system"` — re-applies the DOM class immediately, with no
 * reload. An explicit Dark or Light choice is never overridden by this
 * listener; it only ever updates `systemPrefersDark` for the next time the
 * user switches to System.
 */
watchSystemPrefersDark((prefersDark) => {
  useUiStore.setState({ systemPrefersDark: prefersDark });
  if (useUiStore.getState().theme === "system") {
    applyThemeClass(resolveTheme("system", prefersDark));
  }
});
