import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RuleBuilderForm } from "@/features/alerts/components/RuleBuilderForm";
import { CONDITION_KINDS } from "@/features/alerts/lib/conditions";
import type { AlertRule } from "@/lib/api/alertRules";
import { installAlertsApiMock, alertRule } from "@/test/alertsApiMock";
import { watchlist } from "@/test/watchlistsApiMock";
import { renderWithProviders } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderBuilder(rule?: AlertRule) {
  const onSubmit = vi.fn();
  installAlertsApiMock({
    watchlists: [watchlist({ id: 3, name: "Police Helicopters" })],
  });
  renderWithProviders(
    <RuleBuilderForm
      rule={rule}
      submitLabel={rule ? "Save changes" : "Create rule"}
      isPending={false}
      serverError={null}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit, user: userEvent.setup() };
}

/** Adds one condition through the picker, the way a user does. */
async function addCondition(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
): Promise<void> {
  await user.selectOptions(
    screen.getByLabelText("Add a condition"),
    screen.getByRole("option", { name: label }),
  );
  await user.click(screen.getByRole("button", { name: "Add condition" }));
}

describe("RuleBuilderForm", () => {
  it("offers every condition kind the engine supports", () => {
    renderBuilder();

    const picker = screen.getByLabelText("Add a condition");

    for (const meta of CONDITION_KINDS) {
      expect(
        screen.getByRole("option", { name: meta.label }),
      ).toBeInTheDocument();
    }
    // Plus the "choose one" placeholder.
    expect(picker).toHaveDisplayValue("Choose a condition…");
  });

  it("refuses to submit a rule with no conditions", async () => {
    const { onSubmit, user } = renderBuilder();

    await user.type(screen.getByLabelText("Name"), "Everything");
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    // A rule with no conditions would match every aircraft in the sky, so it
    // must never reach the API — the builder says so instead.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/add at least one condition/i),
    ).toBeInTheDocument();
  });

  it("refuses to submit a rule with no name", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "On any watchlist");
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText("Enter a name.")).toBeInTheDocument();
  });

  it("refuses an inverted distance window and says why", async () => {
    const { onSubmit, user } = renderBuilder();

    await user.type(screen.getByLabelText("Name"), "Far but near");
    await addCondition(user, "Distance");
    await user.type(screen.getByLabelText("At least (nm)"), "40");
    await user.type(screen.getByLabelText("Within (nm)"), "10");
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/can never match/i),
    ).toBeInTheDocument();
  });

  it("stays quiet about errors until the first submit attempt", async () => {
    const { user } = renderBuilder();

    await addCondition(user, "Type code");

    // The type-code field is empty and therefore invalid, but arguing with a
    // field nobody has reached yet is noise.
    expect(screen.queryByText("Enter a type designator.")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(
      await screen.findByText("Enter a type designator."),
    ).toBeInTheDocument();
  });

  it("composes the document the API stores", async () => {
    const { onSubmit, user } = renderBuilder();

    await user.type(screen.getByLabelText("Name"), "  Low military  ");
    await user.selectOptions(screen.getByLabelText("Severity"), "critical");
    await addCondition(user, "Classification");
    await user.click(screen.getByRole("checkbox", { name: "Military" }));
    await addCondition(user, "Altitude");
    await user.type(screen.getByLabelText("At or below (ft)"), "5000");
    await user.click(
      screen.getByRole("checkbox", {
        name: "Also alert for aircraft on the ground",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: "Low military",
      description: null,
      severity: "critical",
      enabled: true,
      conditions: {
        version: 1,
        classification: {
          military: true,
          government: false,
          law_enforcement: false,
        },
        max_alt_ft: 5000,
        applies_on_ground: true,
      },
    });
  });

  it("does not offer a condition kind twice", async () => {
    const { user } = renderBuilder();

    await addCondition(user, "Type code");

    // The stored document is flat, so a second type_code would have nowhere
    // to go — the picker stops offering it rather than silently overwriting.
    expect(screen.queryByRole("option", { name: "Type code" })).toBeNull();
  });

  it("removes a condition again", async () => {
    const { user } = renderBuilder();

    await addCondition(user, "Model");
    expect(screen.getByLabelText("Model contains")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Remove the Model condition" }),
    );

    expect(screen.queryByLabelText("Model contains")).toBeNull();
    expect(screen.getByRole("option", { name: "Model" })).toBeInTheDocument();
  });

  it("offers the watchlists a 'on a watchlist' condition can name", async () => {
    const { user } = renderBuilder();

    await addCondition(user, "On a watchlist");

    expect(
      await screen.findByRole("option", { name: "Police Helicopters" }),
    ).toBeInTheDocument();
  });

  it("loads an existing rule's conditions for editing", async () => {
    const { user, onSubmit } = renderBuilder(
      alertRule({
        id: 7,
        name: "Rare here",
        severity: "interesting",
        conditions: { version: 1, rare_aircraft: { max_sightings: 2 } },
      }),
    );

    expect(screen.getByLabelText("Name")).toHaveValue("Rare here");
    expect(
      screen.getByLabelText("At most this many sightings here"),
    ).toHaveValue("2");

    await user.clear(screen.getByLabelText("At most this many sightings here"));
    await user.type(
      screen.getByLabelText("At most this many sightings here"),
      "5",
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    // Only the threshold moved: the rest of the rule round-tripped untouched.
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Rare here",
        severity: "interesting",
        conditions: { version: 1, rare_aircraft: { max_sightings: 5 } },
      }),
    );
  });

  it("names the severity in words, not by colour alone", () => {
    renderBuilder();

    // SPEC §80: the level is readable as text, and the selector explains what
    // choosing it means.
    expect(screen.getByLabelText("Severity")).toHaveDisplayValue("Interesting");
    expect(
      screen.getByText(/worth a glance when you are already looking/i),
    ).toBeInTheDocument();
  });
});
