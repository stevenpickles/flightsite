import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EnrichmentSection } from "@/features/settings/sections/EnrichmentSection";
import {
  defaultEnrichmentConfig,
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection(hasStoredKey: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig({
    enrichment: defaultEnrichmentConfig({
      aerodatabox_enabled: hasStoredKey,
      aerodatabox_api_key: hasStoredKey ? "•••" : null,
      daily_lookup_budget: 100,
      route_ttl_days: 7,
    }),
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
        enrichment: defaultEnrichmentConfig({
          aerodatabox_enabled: true,
          aerodatabox_api_key: "•••",
          daily_lookup_budget: 100,
        }),
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
        daily_lookup_budget: 100,
        route_ttl_days: 7,
      },
    });
  });

  it("clears a stored key explicitly, sending null, without ever showing the old value", async () => {
    const { fetchMock } = installConfigApiMock({
      secretsSet: { "enrichment.aerodatabox_api_key": true },
      config: {
        enrichment: defaultEnrichmentConfig({
          aerodatabox_enabled: true,
          aerodatabox_api_key: "•••",
          daily_lookup_budget: 100,
        }),
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
      enrichment: {
        aerodatabox_enabled: false,
        aerodatabox_api_key: null,
        daily_lookup_budget: 100,
        route_ttl_days: 7,
      },
    });
  });

  it("omits the key from the payload when the field is left untouched", async () => {
    const { fetchMock } = installConfigApiMock({
      secretsSet: { "enrichment.aerodatabox_api_key": true },
      config: {
        enrichment: defaultEnrichmentConfig({
          aerodatabox_enabled: true,
          aerodatabox_api_key: "•••",
          daily_lookup_budget: 100,
        }),
      },
    });
    renderSection(true);

    // Nothing to save yet — untouched fields never dirty the section.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders the lookup budget and cache lifetime from the config", () => {
    installConfigApiMock();
    renderSection(true);

    expect(screen.getByLabelText(/daily lookup budget/i)).toHaveValue("100");
    expect(screen.getByLabelText(/route cache lifetime/i)).toHaveValue("7");
    // The helper text has to say what is being counted and when it resets —
    // "100 lookups" is meaningless without both.
    expect(screen.getByText(/one call to the provider/i)).toBeInTheDocument();
    expect(screen.getByText(/resets at midnight UTC/i)).toBeInTheDocument();
    expect(screen.getByText(/0 for unlimited/i)).toBeInTheDocument();
  });

  it("carries no restart badge for the budget or the cache lifetime either", () => {
    // Both apply on save for the same reason the key does: the provider is
    // rebuilt, not restarted (slice 069's badge is deliberately absent).
    installConfigApiMock();
    const { container } = renderSection(true);

    expect(screen.getByLabelText(/daily lookup budget/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/route cache lifetime/i)).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/restart/i);
  });

  it("sends the edited budget and cache lifetime in the patch", async () => {
    const { fetchMock } = installConfigApiMock({
      secretsSet: { "enrichment.aerodatabox_api_key": true },
      config: {
        enrichment: defaultEnrichmentConfig({
          aerodatabox_enabled: true,
          aerodatabox_api_key: "•••",
          daily_lookup_budget: 100,
        }),
      },
    });
    const user = userEvent.setup();
    renderSection(true);

    await user.clear(screen.getByLabelText(/daily lookup budget/i));
    await user.type(screen.getByLabelText(/daily lookup budget/i), "250");
    await user.clear(screen.getByLabelText(/route cache lifetime/i));
    await user.type(screen.getByLabelText(/route cache lifetime/i), "14");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as {
      enrichment: Record<string, unknown>;
    };
    expect(body.enrichment.daily_lookup_budget).toBe(250);
    expect(body.enrichment.route_ttl_days).toBe(14);
    // The untouched key is still omitted — the new fields share the section's
    // save, not its secret-handling rules.
    expect(body.enrichment).not.toHaveProperty("aerodatabox_api_key");
  });

  it("accepts 0 as a budget — unlimited is a value, not a blank", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(true);

    await user.clear(screen.getByLabelText(/daily lookup budget/i));
    await user.type(screen.getByLabelText(/daily lookup budget/i), "0");

    expect(screen.queryByText(/whole number of lookups/i)).toBeNull();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
  });

  it("blocks a save on an out-of-range cache lifetime", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(true);

    await user.clear(screen.getByLabelText(/route cache lifetime/i));
    await user.type(screen.getByLabelText(/route cache lifetime/i), "45");

    expect(
      screen.getByText(/whole number of days between 1 and 30/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/route cache lifetime/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("blocks a save on a negative budget", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(true);

    await user.clear(screen.getByLabelText(/daily lookup budget/i));
    await user.type(screen.getByLabelText(/daily lookup budget/i), "-5");

    expect(screen.getByText(/whole number of lookups/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("shows a server-side field error against the field it names", async () => {
    installConfigApiMock();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ["enrichment", "daily_lookup_budget"],
                msg: "Budget exceeds the provider plan.",
                type: "value_error",
              },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSection(true);

    await user.clear(screen.getByLabelText(/daily lookup budget/i));
    await user.type(screen.getByLabelText(/daily lookup budget/i), "9000");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(
      await screen.findByText(/budget exceeds the provider plan/i),
    ).toBeInTheDocument();
  });

  it("disables the enable-enrichment checkbox until a usable key exists", () => {
    installConfigApiMock();
    renderSection(false);

    expect(
      screen.getByRole("checkbox", { name: /enable route enrichment/i }),
    ).toBeDisabled();
  });
});
