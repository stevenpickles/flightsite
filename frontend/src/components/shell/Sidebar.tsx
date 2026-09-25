import { ChevronLeft, ChevronRight, Menu, Radar, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { NAV_ITEMS } from "@/components/shell/nav-items";
import { useFocusTrap } from "@/components/shell/useFocusTrap";
import { useIsMobile } from "@/components/shell/useIsMobile";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/store/useUiStore";

/** The seven-section nav list, shared between the desktop sidebar and the
 * mobile drawer. Desktop alone gets the `collapsed` icon-only variant with
 * tooltips — the mobile drawer, opened deliberately by tapping the rail's
 * menu button, always shows full labels. */
function NavList({ collapsed }: { collapsed: boolean }) {
  return (
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
                    className={cn("size-4 shrink-0", isActive && "text-accent")}
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
  );
}

export function Sidebar() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const isMobile = useIsMobile();
  const { pathname } = useLocation();

  // Mobile-only drawer state. Declared unconditionally (rules of hooks) even
  // though it's inert on desktop — `isMobile` can flip at runtime on a
  // resized/rotated window, and every effect below already guards itself.
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);

  useFocusTrap(drawerRef, isMobile && drawerOpen);

  // Closes on route change (R1-07/R2-08/R3-07/R4-06: "closes on route
  // change/Escape/scrim click"). Adjusted during render rather than in an
  // effect (React's documented pattern for "reset state when a prop
  // changes") so a navigation and the drawer's close both land in the same
  // commit instead of the drawer flashing open-then-closed a frame later.
  const [pathnameAtLastRender, setPathnameAtLastRender] = useState(pathname);
  if (pathname !== pathnameAtLastRender) {
    setPathnameAtLastRender(pathname);
    if (drawerOpen) {
      setDrawerOpen(false);
    }
  }

  // Closes on Escape.
  useEffect(() => {
    if (!drawerOpen) {
      return;
    }
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        setDrawerOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [drawerOpen]);

  // Focus management: move focus into the drawer when it opens, and back to
  // the button that opened it when it closes (including the route-change
  // and Escape paths above, which both just flip this same state).
  useEffect(() => {
    if (!isMobile) {
      return;
    }
    if (drawerOpen) {
      closeButtonRef.current?.focus();
    } else if (wasOpenRef.current) {
      openButtonRef.current?.focus();
    }
    wasOpenRef.current = drawerOpen;
  }, [drawerOpen, isMobile]);

  if (isMobile) {
    return (
      <>
        {/* The default state below `md`: a slim, always-visible rail — not
         * a copy of the desktop collapsed width driven by `sidebarCollapsed`
         * (mobile ignores that preference entirely), and not a full sidebar,
         * so `<main>` stays full width until the drawer is opened. */}
        <div className="flex h-full w-16 flex-col items-center border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
          <div className="flex h-14 shrink-0 items-center justify-center">
            <Radar className="size-6 shrink-0 text-accent" aria-hidden="true" />
          </div>
          <Separator className="bg-sidebar-border" />
          <div className="flex flex-1 flex-col items-center justify-center">
            <Button
              ref={openButtonRef}
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setDrawerOpen(true)}
              aria-expanded={drawerOpen}
              aria-haspopup="dialog"
            >
              <Menu className="size-5" aria-hidden="true" />
              <span className="sr-only">Open navigation menu</span>
            </Button>
          </div>
        </div>

        {drawerOpen && (
          <>
            {/* Scrim — closes on click, per the finding's own wording. */}
            <div
              className="fixed inset-0 z-30 bg-black/50"
              aria-hidden="true"
              onClick={() => setDrawerOpen(false)}
            />
            <div
              ref={drawerRef}
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
              className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground shadow-xl"
            >
              <div className="flex h-14 shrink-0 items-center justify-between gap-2 px-4">
                <div className="flex items-center gap-2">
                  <Radar
                    className="size-6 shrink-0 text-accent"
                    aria-hidden="true"
                  />
                  <span className="text-sm font-semibold tracking-wide">
                    FlightSite
                  </span>
                </div>
                <Button
                  ref={closeButtonRef}
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setDrawerOpen(false)}
                >
                  <X className="size-4" aria-hidden="true" />
                  <span className="sr-only">Close navigation menu</span>
                </Button>
              </div>

              <Separator className="bg-sidebar-border" />

              <NavList collapsed={false} />

              <Separator className="bg-sidebar-border" />

              <div className="flex flex-col gap-2 p-2">
                <ThemeToggle collapsed={false} />
              </div>
            </div>
          </>
        )}
      </>
    );
  }

  // Desktop (`md` and above) — unchanged: a fixed-width column driven only
  // by the persisted `sidebarCollapsed` toggle.
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

      <NavList collapsed={collapsed} />

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
