import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { draftFromConfig } from "@/features/setup/lib/draft";
import { UnitsTimezoneStep } from "@/features/setup/steps/UnitsTimezoneStep";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

const draft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig(),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

describe("UnitsTimezoneStep", () => {
  it("marks the current unit selection", () => {
    render(<UnitsTimezoneStep draft={draft} onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: /aviation/i })).toBeChecked();
    expect(screen.getByRole("radio", { name: /metric/i })).not.toBeChecked();
  });

  it("reports a unit change via onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<UnitsTimezoneStep draft={draft} onChange={onChange} />);

    await user.click(screen.getByRole("radio", { name: /metric/i }));
    expect(onChange).toHaveBeenCalledWith({ units: "metric" });
  });

  it("reports a timezone selection via onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<UnitsTimezoneStep draft={draft} onChange={onChange} />);

    await user.selectOptions(
      screen.getByLabelText(/timezone/i),
      "Europe/London",
    );
    expect(onChange).toHaveBeenCalledWith({ timezone: "Europe/London" });
  });

  it("detects the browser timezone on request", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<UnitsTimezoneStep draft={draft} onChange={onChange} />);

    await user.click(
      screen.getByRole("button", { name: /detect from browser/i }),
    );
    expect(onChange).toHaveBeenCalledWith({ timezone: expect.any(String) });
  });
});
