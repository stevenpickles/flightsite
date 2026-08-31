import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WIZARD_STEPS } from "@/features/setup/constants";
import { WizardProgress } from "@/features/setup/components/WizardProgress";

describe("WizardProgress", () => {
  it("renders every wizard step and marks the current one", () => {
    render(
      <WizardProgress
        currentStepId="decoder"
        furthestStepIndex={2}
        onStepSelect={vi.fn()}
      />,
    );
    for (const step of WIZARD_STEPS) {
      expect(
        screen.getByRole("button", { name: step.label }),
      ).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Decoder" })).toHaveAttribute(
      "aria-current",
      "step",
    );
  });

  it("disables steps beyond the furthest one reached", () => {
    render(
      <WizardProgress
        currentStepId="welcome"
        furthestStepIndex={0}
        onStepSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Welcome" })).toBeEnabled();
  });

  it("selecting a reachable step calls onStepSelect with its id", async () => {
    const user = userEvent.setup();
    const onStepSelect = vi.fn();
    render(
      <WizardProgress
        currentStepId="decoder"
        furthestStepIndex={3}
        onStepSelect={onStepSelect}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Welcome" }));
    expect(onStepSelect).toHaveBeenCalledWith("welcome");
  });
});
