import { create } from "zustand";

import {
  applyThemeClass,
  readStoredTheme,
  writeStoredTheme,
} from "@/lib/theme";
import type { Theme } from "@/lib/theme";

export interface UiState {
  /** Active color theme. Defaults to dark; persisted to localStorage. */
  theme: Theme;
  /** Whether the primary sidebar is collapsed to icon-only width. */
  sidebarCollapsed: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: readStoredTheme(),
  sidebarCollapsed: false,

  setTheme: (theme) => {
    writeStoredTheme(theme);
    applyThemeClass(theme);
    set({ theme });
  },

  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    get().setTheme(next);
  },

  setSidebarCollapsed: (collapsed) => {
    set({ sidebarCollapsed: collapsed });
  },

  toggleSidebar: () => {
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed }));
  },
}));
