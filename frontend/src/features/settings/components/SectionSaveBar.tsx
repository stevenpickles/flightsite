import { Button } from "@/components/ui/button";

export interface SectionSaveBarProps {
  isDirty: boolean;
  isPending: boolean;
  /** True once a save has succeeded and no further edits have been made
   * since — cleared the moment the section becomes dirty again. */
  justSaved: boolean;
  /** A general (non-field) error from the last save attempt, or `null`. */
  errorMessage: string | null;
  /** True while the section has a client-side validation error blocking
   * save, independent of `isDirty`. */
  hasBlockingError: boolean;
  onSave: () => void;
}

/** The Save control shared by every settings section: a status message
 * (unsaved / saved / error) plus the Save button itself, disabled whenever
 * there is nothing to save or a field is currently invalid. */
export function SectionSaveBar({
  isDirty,
  isPending,
  justSaved,
  errorMessage,
  hasBlockingError,
  onSave,
}: SectionSaveBarProps) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
      <div role="status" aria-live="polite" className="text-xs">
        {errorMessage && (
          <p role="alert" className="text-destructive">
            {errorMessage}
          </p>
        )}
        {!errorMessage && isDirty && (
          <p className="text-muted-foreground">Unsaved changes</p>
        )}
        {!errorMessage && !isDirty && justSaved && (
          <p className="text-accent-foreground">Saved</p>
        )}
      </div>
      <Button
        type="button"
        variant="accent"
        size="sm"
        disabled={!isDirty || isPending || hasBlockingError}
        onClick={onSave}
      >
        {isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
