import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ALERT_TEMPLATES,
  DEFAULT_ENABLED_TEMPLATE_IDS,
} from "@/features/setup/constants";
import { draftFromConfig } from "@/features/setup/lib/draft";
import { AlertsStep } from "@/features/setup/steps/AlertsStep";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

const draft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig(),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

describe("AlertsStep", () => {
  it("renders every SPEC §45 template as a checkbox", () => {
    render(<AlertsStep draft={draft} onChange={vi.fn()} />);
    for (const template of ALERT_TEMPLATES) {
      expect(
        screen.getByRole("checkbox", { name: new RegExp(template.label, "i") }),
      ).toBeInTheDocument();
    }
    expect(screen.getAllByRole("checkbox")).toHaveLength(
      ALERT_TEMPLATES.length,
    );
  });

  it("checks emergency_squawk, military, and first_ever by default", () => {
    render(<AlertsStep draft={draft} onChange={vi.fn()} />);
    for (const id of DEFAULT_ENABLED_TEMPLATE_IDS) {
      const template = ALERT_TEMPLATES.find((entry) => entry.id === id);
      expect(
        screen.getByRole("checkbox", {
          name: new RegExp(template!.label, "i"),
        }),
      ).toBeChecked();
    }
    expect(
      screen.getByRole("checkbox", { name: /watchlist/i }),
    ).not.toBeChecked();
  });

  it("adds a template on check and removes it on uncheck", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<AlertsStep draft={draft} onChange={onChange} />);

    await user.click(screen.getByRole("checkbox", { name: /watchlist/i }));
    expect(onChange).toHaveBeenCalledWith({
      enabledTemplateIds: [...draft.enabledTemplateIds, "watchlist"],
    });

    onChange.mockClear();
    await user.click(screen.getByRole("checkbox", { name: /military/i }));
    expect(onChange).toHaveBeenCalledWith({
      enabledTemplateIds: draft.enabledTemplateIds.filter(
        (id) => id !== "military",
      ),
    });
  });
});
