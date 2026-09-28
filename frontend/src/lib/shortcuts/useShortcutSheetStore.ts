import { create } from "zustand";

/**
 * Whether the `?` shortcut sheet (`ShortcutSheet`) is open — global,
 * session-only UI state, deliberately not persisted: the sheet is a lookup a
 * user opens for a few seconds, not a preference to remember across visits.
 * A small store rather than component state because it has two openers that
 * do not share a parent — the `?` key (`useKeyboardShortcuts`, mounted in
 * `AppShell`) and the sidebar's own "Keyboard shortcuts" button (`Sidebar`).
 */
interface ShortcutSheetState {
  open: boolean;
  openSheet: () => void;
  close: () => void;
  toggle: () => void;
}

export const useShortcutSheetStore = create<ShortcutSheetState>((set) => ({
  open: false,
  openSheet: () => set({ open: true }),
  close: () => set({ open: false }),
  toggle: () => set((state) => ({ open: !state.open })),
}));
