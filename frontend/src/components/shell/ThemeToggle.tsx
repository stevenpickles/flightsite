import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Theme } from "@/lib/theme";
import { useUiStore } from "@/store/useUiStore";

export interface ThemeToggleProps {
  /** When true, renders icon-only (used in the collapsed sidebar). */
  collapsed?: boolean;
}

/** Icon and label for each stored preference — `"system"` is what
 * roadmap slice 082 adds to the pre-existing dark/light pair. */
const THEME_PRESENTATION: Record<Theme, { icon: LucideIcon; label: string }> = {
  dark: { icon: Moon, label: "Dark theme" },
  light: { icon: Sun, label: "Light theme" },
  system: { icon: Monitor, label: "System theme" },
};

/**
 * A single button that cycles Dark -> Light -> System -> Dark
 * (`useUiStore.toggleTheme`). A three-way cycle rather than a three-option
 * control keeps the same one-control footprint the pre-082 dark/light
 * toggle had — important in the collapsed sidebar, where there is room for
 * exactly one icon button — while still making System reachable from
 * anywhere the toggle already lives.
 *
 * The accessible name is one `aria-label`, always current, rather than a
 * mix of visible text and an `sr-only` span (SPEC §80: state is carried by
 * text, not by the icon alone) — with three possible states there is no
 * single fixed sr-only phrase that reads correctly regardless of which one
 * is active.
 */
export function ThemeToggle({ collapsed = false }: ThemeToggleProps) {
  const theme = useUiStore((state) => state.theme);
  const toggleTheme = useUiStore((state) => state.toggleTheme);
  const { icon: Icon, label } = THEME_PRESENTATION[theme];

  return (
    <Button
      type="button"
      variant="outline"
      size={collapsed ? "icon" : "default"}
      className={collapsed ? undefined : "w-full justify-start"}
      onClick={toggleTheme}
      aria-label={`Toggle theme (currently ${label}). Click to cycle.`}
    >
      <Icon className="size-4" aria-hidden="true" />
      {!collapsed && <span aria-hidden="true">{label}</span>}
    </Button>
  );
}
