import { create } from "zustand";

/**
 * Whether the "What was that?" dialog (roadmap slice 090) is open.
 *
 * A store rather than dialog state because it has openers that share no
 * parent: the Live Map's map control, the phone layout's Activity sheet, the
 * Activity page header, and the `W` shortcut dispatched from
 * `useKeyboardShortcuts` in `AppShell`. Session-only, like the shortcut
 * sheet's: a lookup opened for a few seconds is not a preference.
 */
interface OverheadState {
  open: boolean;
  openDialog: () => void;
  close: () => void;
}

export const useOverheadStore = create<OverheadState>((set) => ({
  open: false,
  openDialog: () => set({ open: true }),
  close: () => set({ open: false }),
}));
