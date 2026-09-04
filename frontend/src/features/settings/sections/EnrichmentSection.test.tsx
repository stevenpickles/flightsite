import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EnrichmentSection } from "@/features/settings/sections/EnrichmentSection";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection(hasStoredKey: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig({
    enrichment: {
      aerodatabox_enabled: hasStoredKey,
      aerodatabox_api_key: hasStoredKey ? "•••" : null,
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <EnrichmentSection config={config} hasStoredKey={hasStoredKey} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EnrichmentSection", () => {
  it("never renders a stored secret's value — the key field starts empty", () => {
    installConfigApiMock();
    renderSection(true);

    expect(screen.getByLabelText(/api key/i)).toHaveValue("");
    expect(screen.getByText(/a key is currently stored/i)).toBeInTheDocument();
  });

  it("carries no restart-required badge — enrichment applies on save", () => {
    // Slice 069: the backend rebuilds the enrichment provider on save, so
    // this is the one section on the page that changes a startup-built
    // service without a restart. A badge here would be a lie.
    installConfigApiMock();
    const { container } = renderSection(true);

    expect(screen.queryByText(/applies on next restart/i)).toBeNull();
    expect(container).not.toHaveTextContent(/restart/i);
  });

  it("shows 'not configured' when no key is stored", () => {
    installConfigApiMock();
    renderSection(false);

    expect(screen.getByText(/^not configured\.$/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/a key is currently stored/i),
    ).not.toBeInTheDocument();
  });

  it("sends the typed replacement key on save and never echoes it back", async () => {
    const { fetchMock } = installConfigApiMock({
      secretsSet: { "enrichment.aerodatabox_api_key": true },
      config: {
        enrichment: { aerodatabox_enabled: true, aerodatabox_api_key: "•••" },
      },
    });
    const user = userEvent.setup();
    renderSection(true);

    await user.type(screen.getByLabelText(/api key/i), "sk-new-value");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    // The field never re-displays a secret, replaced or not.
    expect(screen.getByLabelText(/api key/i)).toHaveValue("");

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({
      enrichment: {
        aerodatabox_enabled: true,
        aerodatabox_api_key: "sk-new-value",
      },
    });
  });

  it("clears a stored key explicitly, sending null, without ever showing the old value", async () => {
    const { fetchMock } = installConfigApiMock({
      secretsSet: { "enrichment.aerodatabox_api_key": true },
      config: {
        enrichment: { aerodatabox_enabled: true, aerodatabox_api_key: "•••" },
      },
    });
    const user = userEvent.setup();
    renderSection(true);

    await user.click(screen.getByRole("button", { name: /clear stored key/i }));
    expect(screen.getByLabelText(/api key/i)).toHaveValue("");

    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    expect(screen.getByText(/^not configured\.$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({
      enrichment: { aerodatabox_enabled: false, aerodatabox_api_key: null },
    });
  });

  it("omits the key from the payload when the field is left untouched", async () => {
    const { fetchMock } = installConfigApiMock({
      secretsSet: { "enrichment.aerodatabox_api_key": true },
      config: {
        enrichment: { aerodatabox_enabled: true, aerodatabox_api_key: "•••" },
      },
    });
    renderSection(true);

    // Nothing to save yet — untouched fields never dirty the section.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("disables the enable-enrichment checkbox until a usable key exists", () => {
    installConfigApiMock();
    renderSection(false);

    expect(
      screen.getByRole("checkbox", { name: /enable route enrichment/i }),
    ).toBeDisabled();
  });
});
