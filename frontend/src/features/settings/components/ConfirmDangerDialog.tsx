/**
 * A typed-confirmation dialog for one destructive Settings action (SPEC §73,
 * roadmap slice 045's Danger Zone). Mirrors the accessibility shape
 * `FilterDrawer` already establishes for a hand-rolled overlay — `role`
 * `"dialog"`, `aria-modal`, Escape-to-close, focus moved to the panel on
 * open — since the project ships no dialog primitive yet.
 *
 * The confirm button stays disabled until the typed text matches
 * `confirmPhrase` **exactly**, mirroring the backend's own gate
 * (`_require_confirm_phrase` in `backend/src/flightsite/api/internal.py`):
 * a client cannot default its way past either check, and the two staying in
 * sync is what makes a submitted confirmation always succeed rather than
 * bouncing off a 422 the dialog did not anticipate.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDialogFocus } from "@/lib/a11y/useDialogFocus";

export interface ConfirmDangerDialogProps {
  open: boolean;
  onClose: () => void;
  /** Dialog heading, and the destructive action it names. */
  title: string;
  /** Explanation of what the action does — the backup suggestion belongs
   * here, passed by the caller so its wording can name the specific action. */
  children: ReactNode;
  /** The exact phrase the operator must type, character for character. */
  confirmPhrase: string;
  /** Label of the enabled confirm button, e.g. "Clear Metadata Cache". */
  confirmLabel: string;
  /** Label while the mutation is in flight. */
  pendingLabel: string;
  isPending: boolean;
  onConfirm: () => void;
}

/**
 * One typed-confirmation dialog. Rendered by the caller for every action it
 * offers — `open` controls visibility rather than the component owning a
 * portal-level singleton, which keeps each action's copy and phrase
 * co-located with the button that opens it.
 */
export function ConfirmDangerDialog({
  open,
  onClose,
  title,
  children,
  confirmPhrase,
  confirmLabel,
  pendingLabel,
  isPending,
  onConfirm,
}: ConfirmDangerDialogProps) {
  const [typed, setTyped] = useState("");
  // A true modal (`aria-modal="true"`): Tab is trapped inside the panel, and
  // focus returns to the button that opened it on close.
  const panelRef = useDialogFocus<HTMLDivElement>({ open, modal: true });
  const inputRef = useRef<HTMLInputElement>(null);
  const headingId = useId();
  const inputId = useId();

  // Reset the typed text whenever `open` flips closed — including a
  // successful confirm, which closes this dialog through the parent's own
  // state rather than through `onClose` — so the next open never shows a
  // stale phrase. Adjusted during render rather than in an effect: this is
  // React's own pattern for state derived from a prop change, and it avoids
  // the extra render an effect-based `setTyped` would cause
  // (react-hooks/set-state-in-effect).
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (!open) {
      setTyped("");
    }
  }

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const matches = typed === confirmPhrase;

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (matches && !isPending) {
      onConfirm();
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        tabIndex={-1}
        className="w-full max-w-md rounded-lg border-2 border-destructive/40 bg-card p-5 text-card-foreground shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2
          id={headingId}
          className="text-base font-semibold tracking-tight text-destructive"
        >
          {title}
        </h2>

        <div className="mt-2 flex flex-col gap-2 text-sm text-muted-foreground">
          {children}
        </div>

        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-2">
          <Label htmlFor={inputId}>
            Type{" "}
            <span className="font-mono font-semibold">{confirmPhrase}</span> to
            confirm
          </Label>
          <Input
            id={inputId}
            ref={inputRef}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder={confirmPhrase}
          />

          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="destructive"
              size="sm"
              disabled={!matches || isPending}
            >
              {isPending ? pendingLabel : confirmLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
