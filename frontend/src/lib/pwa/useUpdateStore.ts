import { create } from "zustand";

/**
 * Whether a newer build of the app is ready to take over (roadmap slice
 * 084), and how to switch to it — set by `registerServiceWorker` from
 * outside React, read by `UpdatePrompt`.
 *
 * `apply` differs by case, which is why it is stored rather than derived:
 * with a new worker *waiting*, applying it asks that worker to activate and
 * reloads once it has; in a second tab whose worker was already switched by
 * the first, the new worker is in charge and applying is just a reload.
 */
interface UpdateState {
  apply: (() => void) | null;
  dismissed: boolean;
  /** Offers an update; re-offering after a dismissal shows it again. */
  offer: (apply: () => void) => void;
  /** Hides the prompt until the next offer. */
  dismiss: () => void;
}

export const useUpdateStore = create<UpdateState>((set) => ({
  apply: null,
  dismissed: false,
  offer: (apply) => set({ apply, dismissed: false }),
  dismiss: () => set({ dismissed: true }),
}));
