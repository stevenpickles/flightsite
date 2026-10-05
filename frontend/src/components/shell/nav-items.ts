import {
  Activity,
  BarChart3,
  Bell,
  Binoculars,
  HeartPulse,
  type LucideIcon,
  Plane,
  RadioTower,
  Radar,
  Settings as SettingsIcon,
  Wifi,
} from "lucide-react";

export interface NavItem {
  /** Route path, relative to the app root. */
  to: string;
  /** Section title shown in the sidebar and as the placeholder page heading. */
  label: string;
  /** One-line description shown on the section's placeholder page. */
  description: string;
  icon: LucideIcon;
}

/**
 * The app's sidebar sections, in order. Live Map is the index route
 * (SPEC.md §10: the app is a live radar app first).
 *
 * SPEC §10's ten primary sections. Activity, Health and Feeders joined the
 * original seven by the owner's §10 amendment of 2026-09-28 (roadmap slice
 * 082, issue #225): routed since slices 035, 042 and 077 but reached only
 * from in-page links, which the 080 survey
 * (`docs/design/080-feature-program.md` §1) found made all three effectively
 * undiscoverable. Their routes, layouts and in-page entry points are
 * unchanged; Feeders keeps its `/receiver/feeders` path.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    to: "/",
    label: "Live Map",
    description: "Real-time aircraft positions around your receiver.",
    icon: Radar,
  },
  {
    to: "/aircraft",
    label: "Aircraft",
    description: "Every aircraft your receiver has ever seen.",
    icon: Plane,
  },
  {
    to: "/sightings",
    label: "Sightings",
    description: "What the receiver heard, by sighting, aircraft or type.",
    icon: Binoculars,
  },
  {
    to: "/analytics",
    label: "Analytics",
    description: "Traffic trends and activity over time.",
    icon: BarChart3,
  },
  {
    to: "/receiver",
    label: "Receiver",
    description: "Performance and coverage of your own receiver.",
    icon: RadioTower,
  },
  {
    to: "/alerts",
    label: "Alerts",
    description: "Watchlists, rules, and interesting-aircraft notifications.",
    icon: Bell,
  },
  {
    to: "/settings",
    label: "Settings",
    description: "Receiver, units, notifications, and system configuration.",
    icon: SettingsIcon,
  },
  {
    to: "/activity",
    label: "Activity",
    description: "A running feed of notable events across the receiver.",
    icon: Activity,
  },
  {
    to: "/health",
    label: "Health",
    description: "Decoder, database, and system diagnostics.",
    icon: HeartPulse,
  },
  {
    to: "/receiver/feeders",
    label: "Feeders",
    description: "The networks this receiver feeds, and their status.",
    icon: Wifi,
  },
] as const;

/** Looks up a nav item by route path. Throws if the path isn't one of the
 * app's sidebar sections — a programming error, never user input. */
export function requireNavItem(to: string): NavItem {
  const item = NAV_ITEMS.find((entry) => entry.to === to);
  if (!item) {
    throw new Error(`Unknown nav item for route "${to}"`);
  }
  return item;
}
