import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TemplateGallery } from "@/features/alerts/components/TemplateGallery";
import { alertRule, installAlertsApiMock } from "@/test/alertsApiMock";
import { renderWithProviders } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("TemplateGallery", () => {
  it("shows every shipped template with its severity in words", async () => {
    installAlertsApiMock();

    renderWithProviders(<TemplateGallery />);

    const card = await screen.findByRole("article", {
      name: "Military aircraft",
    });
    expect(within(card).getByText("High")).toBeInTheDocument();
    expect(
      screen.getByRole("article", { name: "First-ever aircraft" }),
    ).toBeInTheDocument();
  });

  it("presents the emergency template as a statement, not a switch", async () => {
    installAlertsApiMock();

    renderWithProviders(<TemplateGallery />);

    const card = await screen.findByRole("article", {
      name: "Emergency squawk",
    });
    // SPEC §47: emergency squawks alert without a rule and cannot be turned
    // off, so there is nothing here to enable — not even a disabled button,
    // which would read as "not yet" rather than "never".
    expect(within(card).getByText("Always on")).toBeInTheDocument();
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("adds a rule from a template and marks it added", async () => {
    const user = userEvent.setup();
    installAlertsApiMock();

    renderWithProviders(<TemplateGallery />);
    const card = await screen.findByRole("article", {
      name: "Military aircraft",
    });

    await user.click(
      within(card).getByRole("button", {
        name: "Add a rule from the Military aircraft template",
      }),
    );

    expect(await within(card).findByText("Added")).toBeInTheDocument();
    // The action is gone rather than disabled: the rule now lives on the
    // Rules tab, and there is nothing left to do here.
    expect(
      within(card).queryByRole("button", {
        name: "Add a rule from the Military aircraft template",
      }),
    ).toBeNull();
  });

  it("reads 'added' from the rule that carries the provenance", async () => {
    // Not from local state: a template is added exactly when a rule with its
    // key exists, which is what makes a first-run instantiation show here too.
    installAlertsApiMock({
      rules: [
        alertRule({ name: "Watchlist match", template_key: "watchlist" }),
      ],
    });

    renderWithProviders(<TemplateGallery />);

    const card = await screen.findByRole("article", {
      name: "Watchlist match",
    });
    expect(within(card).getByText("Added")).toBeInTheDocument();
    expect(
      screen.getByRole("article", { name: "Military aircraft" }),
    ).not.toHaveTextContent("Added");
  });

  it("surfaces the backend's refusal to instantiate twice", async () => {
    const user = userEvent.setup();
    // The rule exists but this gallery has not seen it yet — the backend
    // refuses the second instantiation and says so.
    let served = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        const method = (init?.method ?? "GET").toUpperCase();
        const json = (body: unknown, status: number) =>
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          });
        if (url === "/api/internal/alert-templates") {
          return json(
            {
              templates: [
                {
                  key: "military",
                  name: "Military aircraft",
                  description: "Any military aircraft.",
                  severity: "high",
                  builtin: false,
                  conditions: { version: 1 },
                },
              ],
            },
            200,
          );
        }
        if (url === "/api/internal/alert-rules" && method === "GET") {
          const rules = served ? [alertRule({ template_key: "military" })] : [];
          return json({ rules }, 200);
        }
        served = true;
        return json({ detail: "template 'military' already has a rule" }, 409);
      }),
    );

    renderWithProviders(<TemplateGallery />);
    const card = await screen.findByRole("article", {
      name: "Military aircraft",
    });

    await user.click(
      within(card).getByRole("button", {
        name: "Add a rule from the Military aircraft template",
      }),
    );

    expect(
      await screen.findByText("template 'military' already has a rule"),
    ).toBeInTheDocument();
  });

  it("reports a failure to load the catalogue", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 500 })),
    );

    renderWithProviders(<TemplateGallery />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load templates/i,
    );
  });
});
