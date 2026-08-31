import { Button } from "@/components/ui/button";

export interface WizardNavProps {
  isFirstStep: boolean;
  isLastStep: boolean;
  canProceed: boolean;
  isSubmitting: boolean;
  onBack: () => void;
  onNext: () => void;
  onFinish: () => void;
}

/** Back / Next / Finish controls shared by every step. Plain `<button>`
 * elements throughout, so keyboard operation (Tab, Enter, Space) needs no
 * extra wiring. */
export function WizardNav({
  isFirstStep,
  isLastStep,
  canProceed,
  isSubmitting,
  onBack,
  onNext,
  onFinish,
}: WizardNavProps) {
  return (
    <div className="flex items-center justify-between border-t border-border px-4 py-4 sm:px-8">
      <Button
        type="button"
        variant="outline"
        onClick={onBack}
        disabled={isFirstStep || isSubmitting}
      >
        Back
      </Button>
      {isLastStep ? (
        <Button type="button" onClick={onFinish} disabled={isSubmitting}>
          {isSubmitting ? "Finishing setup…" : "Finish setup"}
        </Button>
      ) : (
        <Button type="button" onClick={onNext} disabled={!canProceed}>
          Next
        </Button>
      )}
    </div>
  );
}
