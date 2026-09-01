import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { draftFromConfig } from "@/features/setup/lib/draft";
import { WelcomeStep } from "@/features/setup/steps/WelcomeStep";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

const draft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig(),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

describe("WelcomeStep", () => {
  it("shows a validation error for a blank site name", () => {
    render(
      <WelcomeStep
        draft={{ ...draft, siteName: "" }}
        isFirstRun
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/required/i);
  });

  it("shows no error once a site name is present", () => {
    render(
      <WelcomeStep
        draft={{ ...draft, siteName: "Home" }}
        isFirstRun
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports edits via onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <WelcomeStep
        draft={{ ...draft, siteName: "" }}
        isFirstRun
        onChange={onChange}
      />,
    );

    await user.type(screen.getByLabelText(/site name/i), "H");
    expect(onChange).toHaveBeenCalledWith({ siteName: "H" });
  });

  it("shows different copy for first-run vs. edit mode", () => {
    const { rerender } = render(
      <WelcomeStep draft={draft} isFirstRun onChange={vi.fn()} />,
    );
    expect(screen.getByText(/welcome to flightsite/i)).toBeInTheDocument();

    rerender(
      <WelcomeStep draft={draft} isFirstRun={false} onChange={vi.fn()} />,
    );
    expect(screen.getByText(/update your setup/i)).toBeInTheDocument();
  });
});
