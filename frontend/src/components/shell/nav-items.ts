import {
  BarChart3,
  Bell,
  Binoculars,
  type LucideIcon,
  Plane,
  RadioTower,
  Radar,
  Settings as SettingsIcon,
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

/** The seven primary sections of the app, in sidebar order. Live Map is the
 * index route (SPEC.md §10: the app is a live radar app first). */
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
    description: "A chronological log of observation periods.",
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
] as const;

/** Looks up a nav item by route path. Throws if the path isn't one of the
 * seven primary sections — a programming error, never user input. */
export function requireNavItem(to: string): NavItem {
  const item = NAV_ITEMS.find((entry) => entry.to === to);
  if (!item) {
    throw new Error(`Unknown nav item for route "${to}"`);
  }
  return item;
}
