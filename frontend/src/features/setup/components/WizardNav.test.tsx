import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WizardNav } from "@/features/setup/components/WizardNav";

describe("WizardNav", () => {
  it("disables Back on the first step", () => {
    render(
      <WizardNav
        isFirstStep
        isLastStep={false}
        canProceed
        isSubmitting={false}
        onBack={vi.fn()}
        onNext={vi.fn()}
        onFinish={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /back/i })).toBeDisabled();
  });

  it("shows Next (disabled when the step is invalid) on a non-final step", () => {
    render(
      <WizardNav
        isFirstStep={false}
        isLastStep={false}
        canProceed={false}
        isSubmitting={false}
        onBack={vi.fn()}
        onNext={vi.fn()}
        onFinish={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /finish setup/i }),
    ).not.toBeInTheDocument();
  });

  it("shows Finish setup instead of Next on the last step", () => {
    render(
      <WizardNav
        isFirstStep={false}
        isLastStep
        canProceed
        isSubmitting={false}
        onBack={vi.fn()}
        onNext={vi.fn()}
        onFinish={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: /finish setup/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^next$/i }),
    ).not.toBeInTheDocument();
  });

  it("calls onNext / onBack / onFinish on click", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    const onNext = vi.fn();
    render(
      <WizardNav
        isFirstStep={false}
        isLastStep={false}
        canProceed
        isSubmitting={false}
        onBack={onBack}
        onNext={onNext}
        onFinish={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /back/i }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("disables Finish and shows a submitting label while submitting", () => {
    render(
      <WizardNav
        isFirstStep={false}
        isLastStep
        canProceed
        isSubmitting
        onBack={vi.fn()}
        onNext={vi.fn()}
        onFinish={vi.fn()}
      />,
    );
    const button = screen.getByRole("button", { name: /finishing setup/i });
    expect(button).toBeDisabled();
  });
});
