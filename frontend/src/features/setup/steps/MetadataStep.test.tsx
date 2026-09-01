import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { draftFromConfig } from "@/features/setup/lib/draft";
import { MetadataStep } from "@/features/setup/steps/MetadataStep";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

const draft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig(),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

describe("MetadataStep", () => {
  it("shows the metadata informational card", () => {
    render(
      <MetadataStep draft={draft} hasStoredKey={false} onChange={vi.fn()} />,
    );
    expect(screen.getByText(/aircraft metadata/i)).toBeInTheDocument();
    expect(
      screen.getByText(/downloaded from settings after setup/i),
    ).toBeInTheDocument();
  });

  it("disables the enrichment checkbox when there is no usable key", () => {
    render(
      <MetadataStep draft={draft} hasStoredKey={false} onChange={vi.fn()} />,
    );
    expect(
      screen.getByRole("checkbox", { name: /enable route enrichment/i }),
    ).toBeDisabled();
  });

  it("marks the key input touched and enables enrichment once a key is typed", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MetadataStep draft={draft} hasStoredKey={false} onChange={onChange} />,
    );

    await user.type(screen.getByLabelText(/api key/i), "s");
    expect(onChange).toHaveBeenCalledWith({
      aerodataboxKeyInput: "s",
      aerodataboxKeyTouched: true,
      aerodataboxEnabled: true,
    });
  });

  it("shows a 'stored' hint and clear affordance when a key already exists server-side", () => {
    render(<MetadataStep draft={draft} hasStoredKey onChange={vi.fn()} />);
    expect(screen.getByText(/a key is currently stored/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /clear stored key/i }),
    ).toBeInTheDocument();
  });

  it("clearing a stored key touches the field and disables enrichment", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MetadataStep draft={draft} hasStoredKey onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: /clear stored key/i }));
    expect(onChange).toHaveBeenCalledWith({
      aerodataboxKeyInput: "",
      aerodataboxKeyTouched: true,
      aerodataboxEnabled: false,
    });
  });
});
