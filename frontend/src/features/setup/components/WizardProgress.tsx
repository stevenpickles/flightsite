import { CheckCircle2, Circle } from "lucide-react";

import { WIZARD_STEPS, type WizardStepId } from "@/features/setup/constants";
import { cn } from "@/lib/utils";

export interface WizardProgressProps {
  currentStepId: WizardStepId;
  /** Index of the furthest step the user has reached — steps beyond it
   * aren't selectable yet, since their validity hasn't been established. */
  furthestStepIndex: number;
  onStepSelect: (stepId: WizardStepId) => void;
}

/**
 * The wizard's step-progress indicator: a horizontal, keyboard-navigable
 * list of `<button>`s (native tab order, `Enter`/`Space` activation —
 * nothing custom to wire up). Already-completed steps are freely
 * revisitable; steps beyond the furthest one reached are disabled rather
 * than hidden, so the full shape of the wizard stays visible throughout.
 */
export function WizardProgress({
  currentStepId,
  furthestStepIndex,
  onStepSelect,
}: WizardProgressProps) {
  return (
    <nav
      aria-label="Setup steps"
      className="border-b border-border px-4 py-3 sm:px-8"
    >
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-xs sm:text-sm">
        {WIZARD_STEPS.map((step, index) => {
          const isCurrent = step.id === currentStepId;
          const isReachable = index <= furthestStepIndex;
          const isComplete = index < furthestStepIndex;
          return (
            <li key={step.id} className="flex items-center">
              <button
                type="button"
                disabled={!isReachable}
                aria-current={isCurrent ? "step" : undefined}
                onClick={() => {
                  onStepSelect(step.id);
                }}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2 py-1 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
                  isCurrent
                    ? "bg-accent text-accent-foreground"
                    : isReachable
                      ? "text-foreground hover:bg-secondary"
                      : "text-muted-foreground",
                )}
              >
                {isComplete ? (
                  <CheckCircle2 className="size-3.5" aria-hidden="true" />
                ) : (
                  <Circle className="size-3.5" aria-hidden="true" />
                )}
                {step.label}
              </button>
              {index < WIZARD_STEPS.length - 1 && (
                <span
                  aria-hidden="true"
                  className="mx-1 text-muted-foreground sm:mx-2"
                >
                  /
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
