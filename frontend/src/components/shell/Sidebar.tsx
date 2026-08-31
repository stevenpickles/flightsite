import { ChevronLeft, ChevronRight, Radar } from "lucide-react";
import { NavLink } from "react-router-dom";

import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { NAV_ITEMS } from "@/components/shell/nav-items";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/store/useUiStore";

export function Sidebar() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);

  return (
    <div
      className={cn(
        "flex h-full flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-150",
        collapsed ? "w-16" : "w-64",
      )}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center gap-2 px-4",
          collapsed && "justify-center px-0",
        )}
      >
        <Radar className="size-6 shrink-0 text-accent" aria-hidden="true" />
        {!collapsed && (
          <span className="text-sm font-semibold tracking-wide">
            FlightSite
          </span>
        )}
      </div>

      <Separator className="bg-sidebar-border" />

      <nav aria-label="Primary" className="flex-1 overflow-y-auto py-3">
        <ul className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const link = (
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    collapsed && "justify-center px-0 py-2.5",
                    isActive
                      ? "bg-accent/15 text-accent"
                      : "text-sidebar-foreground/80 hover:bg-secondary hover:text-sidebar-foreground",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon
                      className={cn(
                        "size-4 shrink-0",
                        isActive && "text-accent",
                      )}
                      aria-hidden="true"
                    />
                    <span className={collapsed ? "sr-only" : undefined}>
                      {item.label}
                    </span>
                  </>
                )}
              </NavLink>
            );

            return (
              <li key={item.to}>
                {collapsed ? (
                  <Tooltip>
                    <TooltipTrigger asChild>{link}</TooltipTrigger>
                    <TooltipContent side="right">{item.label}</TooltipContent>
                  </Tooltip>
                ) : (
                  link
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      <Separator className="bg-sidebar-border" />

      <div
        className={cn("flex flex-col gap-2 p-2", collapsed && "items-center")}
      >
        <ThemeToggle collapsed={collapsed} />
        <Button
          type="button"
          variant="ghost"
          size={collapsed ? "icon" : "default"}
          className={collapsed ? undefined : "w-full justify-start"}
          onClick={toggleSidebar}
          aria-pressed={collapsed}
        >
          {collapsed ? (
            <ChevronRight className="size-4" aria-hidden="true" />
          ) : (
            <ChevronLeft className="size-4" aria-hidden="true" />
          )}
          {!collapsed && <span>Collapse</span>}
          <span className="sr-only">
            {collapsed ? "Expand sidebar" : "Collapse sidebar"}
          </span>
        </Button>
      </div>
    </div>
  );
}
