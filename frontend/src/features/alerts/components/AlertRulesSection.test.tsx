import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlertRulesSection } from "@/features/alerts/components/AlertRulesSection";
import { alertRule, installAlertsApiMock } from "@/test/alertsApiMock";
import { renderWithProviders } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AlertRulesSection", () => {
  it("invites a first rule when there are none", async () => {
    installAlertsApiMock();

    renderWithProviders(<AlertRulesSection />);

    expect(
      await screen.findByText(/no alert rules yet/i),
    ).toBeInTheDocument();
  });

  it("lists a rule with its severity, status and conditions", async () => {
    installAlertsApiMock({
      rules: [
        alertRule({
          name: "Military aircraft",
          severity: "high",
          description: "Anything military",
        }),
      ],
    });

    renderWithProviders(<AlertRulesSection />);

    const card = await screen.findByRole("article", {
      name: "Military aircraft",
    });
    expect(within(card).getByText("High")).toBeInTheDocument();
    expect(within(card).getByText("Enabled")).toBeInTheDocument();
    expect(within(card).getByText("Anything military")).toBeInTheDocument();
    // The conditions are the backend's own prose, so this card, a
    // notification and the history all say the same thing about the rule.
    expect(within(card).getByText("military")).toBeInTheDocument();
  });

  it("names the template a shipped rule came from", async () => {
    installAlertsApiMock({
      rules: [alertRule({ name: "Military aircraft", template_key: "military" })],
    });

    renderWithProviders(<AlertRulesSection />);

    expect(
      await screen.findByText("From template: Military aircraft"),
    ).toBeInTheDocument();
  });

  it("creates a rule from the builder and shows it in the list", async () => {
    const user = userEvent.setup();
    installAlertsApiMock();

    renderWithProviders(<AlertRulesSection />);
    await screen.findByText(/no alert rules yet/i);

    await user.click(screen.getByRole("button", { name: "New rule" }));
    await user.type(screen.getByLabelText("Name"), "Rare visitors");
    await user.selectOptions(
      screen.getByLabelText("Add a condition"),
      screen.getByRole("option", { name: "Rare airframe" }),
    );
    await user.click(screen.getByRole("button", { name: "Add condition" }));
    await user.type(
      screen.getByLabelText("At most this many sightings here"),
      "2",
    );
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    // The round trip the roadmap asks for: what the builder composed is what
    // the API stored, described back in the API's own words.
    const card = await screen.findByRole("article", { name: "Rare visitors" });
    expect(
      within(card).getByText("seen at most 2 time(s) here"),
    ).toBeInTheDocument();
    // The builder closes once the rule exists.
    expect(screen.getByRole("button", { name: "New rule" })).toBeInTheDocument();
  });

  it("turns a rule off and on again", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({ rules: [alertRule({ name: "Military aircraft" })] });

    renderWithProviders(<AlertRulesSection />);
    await screen.findByRole("article", { name: "Military aircraft" });

    await user.click(
      screen.getByRole("button", { name: "Disable Military aircraft" }),
    );

    // Status is a word, never a colour alone (SPEC §80).
    expect(await screen.findByText("Disabled")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Enable Military aircraft" }),
    );

    expect(await screen.findByText("Enabled")).toBeInTheDocument();
  });

  it("keeps a shipped rule's provenance when it is retuned", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({
      rules: [
        alertRule({
          name: "Locally rare",
          template_key: "locally_rare",
          conditions: { version: 1, rare_aircraft: { max_sightings: 2 } },
        }),
      ],
    });

    renderWithProviders(<AlertRulesSection />);
    await screen.findByRole("article", { name: "Locally rare" });

    await user.click(screen.getByRole("button", { name: "Edit Locally rare" }));
    await user.clear(screen.getByLabelText("At most this many sightings here"));
    await user.type(
      screen.getByLabelText("At most this many sightings here"),
      "5",
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("seen at most 5 time(s) here"),
    ).toBeInTheDocument();
    // SPEC §45's "enable, then customize": tuning does not erase where the
    // rule came from.
    expect(screen.getByText(/from template/i)).toBeInTheDocument();
  });

  it("deletes a rule once the warning is accepted", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({ rules: [alertRule({ name: "Military aircraft" })] });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderWithProviders(<AlertRulesSection />);
    await screen.findByRole("article", { name: "Military aircraft" });

    await user.click(
      screen.getByRole("button", { name: "Delete Military aircraft" }),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("article", { name: "Military aircraft" }),
      ).toBeNull();
    });
  });

  it("keeps a rule when the deletion warning is declined", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({ rules: [alertRule({ name: "Military aircraft" })] });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    renderWithProviders(<AlertRulesSection />);
    await screen.findByRole("article", { name: "Military aircraft" });

    await user.click(
      screen.getByRole("button", { name: "Delete Military aircraft" }),
    );

    expect(
      screen.getByRole("article", { name: "Military aircraft" }),
    ).toBeInTheDocument();
  });

  it("surfaces the backend's own rejection of a write", async () => {
    const user = userEvent.setup();
    // A rule the list still shows but the backend no longer has — what a
    // second browser tab deleting it looks like from here. The backend stays
    // authoritative and its answer is shown rather than swallowed.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        const method = (init?.method ?? "GET").toUpperCase();
        if (url === "/api/internal/alert-rules" && method === "GET") {
          return new Response(
            JSON.stringify({ rules: [alertRule({ name: "Military aircraft" })] }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url === "/api/internal/alert-templates") {
          return new Response(JSON.stringify({ templates: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(
          JSON.stringify({ detail: "no alert rule with id 1" }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    renderWithProviders(<AlertRulesSection />);
    await screen.findByRole("article", { name: "Military aircraft" });

    await user.click(
      screen.getByRole("button", { name: "Disable Military aircraft" }),
    );

    expect(
      await screen.findByText("no alert rule with id 1"),
    ).toBeInTheDocument();
  });

  it("reports a failure to load the rules", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 500 })),
    );

    renderWithProviders(<AlertRulesSection />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load alert rules/i,
    );
  });
});
