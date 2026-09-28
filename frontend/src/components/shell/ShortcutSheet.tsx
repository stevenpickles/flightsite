/**
 * The `?` shortcut sheet (roadmap slice 082, issue #225, SPEC §80): a modal
 * dialog listing exactly the bindings `lib/shortcuts/registry.ts` declares —
 * the one list `useKeyboardShortcuts` also reads, so the sheet can never
 * claim a binding that does not exist or omit one that does.
 *
 * Mirrors `ConfirmDangerDialog`'s hand-rolled dialog shape (this project
 * ships no dialog primitive): `role="dialog"`, `aria-modal="true"`, and
 * `useDialogFocus`'s focus trap. Escape is scoped to the panel itself via
 * `onKeyDown` (bubbling through React's synthetic event system, which stops
 * the underlying native event from reaching a `window`-level listener once
 * `stopPropagation` is called) rather than a second `window` listener — a
 * `window` listener would also reach `AircraftDetailPanel`'s own Escape
 * handler and deselect whatever aircraft was selected before this sheet was
 * opened, which closing a shortcut lookup should never do.
 */
import { X } from "lucide-react";
import { useEffect, useId } from "react";

import { useDialogFocus } from "@/lib/a11y/useDialogFocus";
import { SHORTCUTS, type ShortcutGroup } from "@/lib/shortcuts/registry";
import { useShortcutSheetStore } from "@/lib/shortcuts/useShortcutSheetStore";

const GROUPS: readonly ShortcutGroup[] = ["Live Map", "Go to…", "General"];

export function ShortcutSheet() {
  const open = useShortcutSheetStore((state) => state.open);
  const close = useShortcutSheetStore((state) => state.close);
  const headingId = useId();
  const panelRef = useDialogFocus<HTMLDivElement>({ open, modal: true });

  useEffect(() => {
    if (open) {
      panelRef.current?.focus();
    }
  }, [open, panelRef]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={close}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        tabIndex={-1}
        data-testid="shortcut-sheet"
        className="flex max-h-[85vh] w-full max-w-md flex-col overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-xl"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            close();
          }
        }}
      >
        <header className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 id={headingId} className="text-sm font-semibold">
            Keyboard shortcuts
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close keyboard shortcuts"
            className="rounded-md p-1.5 text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </header>

        <div className="overflow-y-auto px-4 py-3">
          <p className="mb-3 text-xs text-muted-foreground">
            Suspended while typing in a field. Every shortcut below also has a
            visible control that does the same thing.
          </p>
          {GROUPS.map((group) => (
            <div key={group} className="mb-4 last:mb-0">
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group}
              </h3>
              <dl className="flex flex-col gap-1.5">
                {SHORTCUTS.filter((shortcut) => shortcut.group === group).map(
                  (shortcut) => (
                    <div
                      key={shortcut.id}
                      className="flex items-center justify-between gap-3 text-sm"
                    >
                      <dt className="text-foreground">
                        {shortcut.description}
                      </dt>
                      <dd>
                        <kbd className="rounded border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] tracking-wide">
                          {shortcut.keys}
                        </kbd>
                      </dd>
                    </div>
                  ),
                )}
              </dl>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
