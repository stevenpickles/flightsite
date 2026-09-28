/**
 * The one list of every keyboard shortcut FlightSite binds (roadmap slice
 * 082, issue #225, SPEC §80). `ShortcutSheet` renders exactly this list and
 * `useKeyboardShortcuts` implements exactly these keys — two readers of one
 * source, so the sheet can never claim a binding that does not exist or omit
 * one that does. `Esc` is included for documentation even though
 * `AircraftDetailPanel` implements it directly (existing behaviour, kept
 * unchanged by this slice) rather than through this dispatcher.
 */

export type ShortcutGroup = "Live Map" | "Go to…" | "General";

export interface ShortcutDescriptor {
  /** Stable id, for `key` props and tests — never shown. */
  id: string;
  /** Display form for the sheet, e.g. "/" or "G  then  M". */
  keys: string;
  description: string;
  group: ShortcutGroup;
}

export const SHORTCUTS: readonly ShortcutDescriptor[] = [
  {
    id: "focus-search",
    keys: "/",
    description: "Focus the live aircraft search",
    group: "Live Map",
  },
  {
    id: "toggle-layers",
    keys: "L",
    description: "Toggle the Layers card",
    group: "Live Map",
  },
  {
    id: "toggle-filters",
    keys: "F",
    description: "Toggle the filter drawer",
    group: "Live Map",
  },
  {
    id: "deselect",
    keys: "Esc",
    description: "Deselect the current aircraft",
    group: "Live Map",
  },
  {
    id: "recenter",
    keys: "H",
    description: "Recentre the map on the receiver",
    group: "Live Map",
  },
  {
    id: "prev-interesting",
    keys: "[",
    description: "Select the previous interesting aircraft",
    group: "Live Map",
  },
  {
    id: "next-interesting",
    keys: "]",
    description: "Select the next interesting aircraft",
    group: "Live Map",
  },
  {
    id: "go-map",
    keys: "G  then  M",
    description: "Go to Live Map",
    group: "Go to…",
  },
  {
    id: "go-aircraft",
    keys: "G  then  A",
    description: "Go to Aircraft",
    group: "Go to…",
  },
  {
    id: "go-sightings",
    keys: "G  then  S",
    description: "Go to Sightings",
    group: "Go to…",
  },
  {
    id: "go-analytics",
    keys: "G  then  N",
    description: "Go to Analytics",
    group: "Go to…",
  },
  {
    id: "go-receiver",
    keys: "G  then  R",
    description: "Go to Receiver",
    group: "Go to…",
  },
  {
    id: "go-alerts",
    keys: "G  then  L",
    description: "Go to Alerts",
    group: "Go to…",
  },
  {
    id: "go-settings",
    keys: "G  then  T",
    description: "Go to Settings",
    group: "Go to…",
  },
  {
    id: "go-activity",
    keys: "G  then  V",
    description: "Go to Activity",
    group: "Go to…",
  },
  {
    id: "go-health",
    keys: "G  then  H",
    description: "Go to Health",
    group: "Go to…",
  },
  {
    id: "go-feeders",
    keys: "G  then  F",
    description: "Go to Feeders",
    group: "Go to…",
  },
  {
    id: "shortcut-sheet",
    keys: "?",
    description: "Show this shortcut list",
    group: "General",
  },
] as const;

/** The `g`-sequence's second key, lower-cased, to the route it navigates
 * to — the single source `useKeyboardShortcuts` reads and the "Go to…"
 * rows above describe. */
export const NAVIGATION_LETTERS: Readonly<Record<string, string>> = {
  m: "/",
  a: "/aircraft",
  s: "/sightings",
  n: "/analytics",
  r: "/receiver",
  l: "/alerts",
  t: "/settings",
  v: "/activity",
  h: "/health",
  f: "/receiver/feeders",
};
