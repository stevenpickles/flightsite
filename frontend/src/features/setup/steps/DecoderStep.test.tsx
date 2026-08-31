import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { draftFromConfig } from "@/features/setup/lib/draft";
import { DecoderStep } from "@/features/setup/steps/DecoderStep";
import {
  INITIAL_DECODER_TEST_STATE,
  type DecoderTestState,
  type WizardDraft,
} from "@/features/setup/types";
import {
  defaultFlightSiteConfig,
  failureConnectionTestResult,
  installConfigApiMock,
  successConnectionTestResult,
} from "@/test/configApiMock";
import { renderWithProviders } from "@/test/test-utils";

const baseDraft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig(),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Manages both `draft` and `testState` locally, so a simulated field edit
 * actually changes the prop `DecoderStep` reacts to — a static `draft`
 * object with a no-op `onChange` would never trigger the component's
 * reset-on-edit effect. */
function Harness({
  draft = baseDraft,
  initialState = INITIAL_DECODER_TEST_STATE,
}: {
  draft?: WizardDraft;
  initialState?: DecoderTestState;
}) {
  const [currentDraft, setDraft] = useState(draft);
  const [testState, setTestState] = useState(initialState);
  return (
    <DecoderStep
      draft={currentDraft}
      onChange={(patch) => {
        setDraft((current) => ({ ...current, ...patch }));
      }}
      testState={testState}
      onTestStateChange={setTestState}
    />
  );
}

describe("DecoderStep", () => {
  it("shows validation errors for invalid fields", () => {
    renderWithProviders(<Harness draft={{ ...baseDraft, receiverHost: "" }} />);
    expect(screen.getByText(/host is required/i)).toBeInTheDocument();
  });

  it("disables Test connection until the fields are valid", () => {
    renderWithProviders(
      <Harness draft={{ ...baseDraft, receiverPort: "0" }} />,
    );
    expect(
      screen.getByRole("button", { name: /test connection/i }),
    ).toBeDisabled();
  });

  it("runs a successful connection test and reports the outcome", async () => {
    installConfigApiMock({ decoderTestResult: successConnectionTestResult() });
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: /test connection/i }));

    expect(
      await screen.findByText(/connected — found readsb/i),
    ).toBeInTheDocument();
  });

  it("runs a failed connection test and reports the error detail", async () => {
    installConfigApiMock({
      decoderTestResult: failureConnectionTestResult({
        error: "unreachable",
        detail: "Connection refused",
      }),
    });
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: /test connection/i }));

    expect(
      await screen.findByText(/unreachable: connection refused/i),
    ).toBeInTheDocument();
  });

  it("lets the user explicitly skip the test", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: /skip test/i }));

    expect(screen.getByText(/test skipped/i)).toBeInTheDocument();
  });

  it("resets a completed test outcome once a tested field is edited", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <Harness
        initialState={{
          status: "success",
          skipped: false,
          message: "Connected — ok",
        }}
      />,
    );
    expect(screen.getByText(/connected — ok/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^host$/i), "x");

    expect(screen.queryByText(/connected — ok/i)).not.toBeInTheDocument();
    expect(screen.getByText(/not tested yet/i)).toBeInTheDocument();
  });
});
