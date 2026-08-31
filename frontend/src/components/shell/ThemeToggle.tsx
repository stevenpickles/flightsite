import { Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useUiStore } from "@/store/useUiStore";

export interface ThemeToggleProps {
  /** When true, renders icon-only (used in the collapsed sidebar). */
  collapsed?: boolean;
}

export function ThemeToggle({ collapsed = false }: ThemeToggleProps) {
  const theme = useUiStore((state) => state.theme);
  const toggleTheme = useUiStore((state) => state.toggleTheme);
  const isDark = theme === "dark";

  return (
    <Button
      type="button"
      variant="outline"
      size={collapsed ? "icon" : "default"}
      className={collapsed ? undefined : "w-full justify-start"}
      onClick={toggleTheme}
      aria-pressed={isDark}
    >
      {isDark ? (
        <Moon className="size-4" aria-hidden="true" />
      ) : (
        <Sun className="size-4" aria-hidden="true" />
      )}
      {!collapsed && <span>{isDark ? "Dark theme" : "Light theme"}</span>}
      <span className="sr-only">Toggle theme</span>
    </Button>
  );
}
