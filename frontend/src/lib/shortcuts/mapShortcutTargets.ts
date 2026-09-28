/**
 * A small bridge from the Live Map's own components to the app-wide
 * keyboard dispatcher, mirroring `lib/navigation.ts`'s one-slot pattern for
 * the same reason (ADR-0015's precedent): the state a shortcut needs to flip
 * — `FilterDrawer`'s open flag, `LayersControl`'s — lives in components
 * mounted only on the Live Map, while `useKeyboardShortcuts` that decides
 * *whether* a keypress should reach them is mounted for the life of the
 * session in `AppShell`. Each field is independently registered on mount and
 * cleared on unmount by the one component that owns it; reading a field
 * nobody has registered (any other route, or a render before that component
 * has mounted) is a safe no-op — every call site uses `?.()`.
 */

export interface MapShortcutTargets {
  toggleLayersCard?: () => void;
  toggleFilterDrawer?: () => void;
  focusLiveSearch?: () => void;
}

const targets: MapShortcutTargets = {};

export function setMapShortcutTarget<K extends keyof MapShortcutTargets>(
  key: K,
  fn: MapShortcutTargets[K] | undefined,
): void {
  targets[key] = fn;
}

export function getMapShortcutTargets(): Readonly<MapShortcutTargets> {
  return targets;
}
