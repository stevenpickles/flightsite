import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { draftFromConfig } from "@/features/setup/lib/draft";
import { NotificationsStep } from "@/features/setup/steps/NotificationsStep";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

const draft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig(),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

describe("NotificationsStep", () => {
  it("reflects the default severities (info off, the rest on)", () => {
    render(<NotificationsStep draft={draft} onChange={vi.fn()} />);
    expect(
      screen.getByRole("checkbox", { name: /enable browser notifications/i }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /info/i })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /critical/i })).toBeChecked();
  });

  it("disables the per-severity checkboxes when the master toggle is off", () => {
    render(
      <NotificationsStep
        draft={{
          ...draft,
          notifications: { ...draft.notifications, enabled: false },
        }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: /critical/i })).toBeDisabled();
  });

  it("reports the master toggle change via onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<NotificationsStep draft={draft} onChange={onChange} />);

    await user.click(
      screen.getByRole("checkbox", { name: /enable browser notifications/i }),
    );
    expect(onChange).toHaveBeenCalledWith({
      notifications: { ...draft.notifications, enabled: false },
    });
  });

  it("reports a per-severity change via onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<NotificationsStep draft={draft} onChange={onChange} />);

    await user.click(screen.getByRole("checkbox", { name: /info/i }));
    expect(onChange).toHaveBeenCalledWith({
      notifications: { ...draft.notifications, info: true },
    });
  });
});
