/**
 * The rule builder's version 2 editors (roadmap slice 089): squawk and
 * emitter-category chips, callsign/registration patterns, ground-speed and
 * vertical-rate windows with their R4-13 conversion hints, and the area
 * editor's keyboard fallback — each driven the way a user drives it, and
 * each ending in the document the API stores.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RuleBuilderForm } from "@/features/alerts/components/RuleBuilderForm";
import { installAlertsApiMock, alertRule } from "@/test/alertsApiMock";
import { resetMapLibreMock } from "@/test/maplibreGlMock";
import { renderWithProviders } from "@/test/test-utils";
import type { AlertRule } from "@/lib/api/alertRules";

beforeEach(() => {
  resetMapLibreMock();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderBuilder(
  options: { rule?: AlertRule; units?: "metric" | "aviation" } = {},
) {
  const onSubmit = vi.fn();
  installAlertsApiMock({ units: options.units ?? "aviation" });
  renderWithProviders(
    <RuleBuilderForm
      rule={options.rule}
      submitLabel={options.rule ? "Save changes" : "Create rule"}
      isPending={false}
      serverError={null}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit, user: userEvent.setup() };
}

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

async function submit(user: ReturnType<typeof userEvent.setup>, name = "Rule") {
  await user.type(screen.getByLabelText("Name"), name);
  await user.click(screen.getByRole("button", { name: /Create rule|Save/ }));
}

describe("RuleBuilderForm — version 2 conditions", () => {
  it("adds squawk codes as chips and refuses a non-octal one on the spot", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "Squawk code");
    const box = screen.getByLabelText("Squawk codes");
    await user.type(box, "7800{Enter}");

    expect(screen.getByText(/four digits, each 0–7/)).toBeInTheDocument();

    await user.clear(box);
    await user.type(box, "7000 1200{Enter}");
    expect(
      screen.getByRole("button", { name: "Remove 7000" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove 7000" }));
    await user.type(box, "0020,");

    await submit(user);

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        conditions: { version: 2, squawk_in: ["0020", "1200"] },
      }),
    );
  });

  it("removes the last chip with Backspace in an empty box", async () => {
    const { user } = renderBuilder();

    await addCondition(user, "Squawk code");
    const box = screen.getByLabelText("Squawk codes");
    await user.type(box, "7000{Enter}{Backspace}");

    expect(screen.queryByRole("button", { name: "Remove 7000" })).toBeNull();
  });

  it("refuses to submit an empty squawk set", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "Squawk code");
    await submit(user);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Add at least one squawk code."),
    ).toBeInTheDocument();
  });

  it("names emitter categories in words and upper-cases what is typed", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "Emitter category");
    await user.type(screen.getByLabelText("Emitter categories"), "a7{Enter}");

    expect(screen.getByText("A7 · Rotorcraft")).toBeInTheDocument();

    await submit(user);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        conditions: { version: 2, emitter_category_in: ["A7"] },
      }),
    );
  });

  it("explains the callsign pattern syntax and sends the pattern trimmed", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "Callsign pattern");
    const field = screen.getByLabelText("Callsign matches");
    expect(field).toHaveAccessibleDescription(
      /stands for any run of characters/,
    );

    await user.type(field, " RCH* ");
    await submit(user);

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        conditions: { version: 2, callsign_glob: "RCH*" },
      }),
    );
  });

  it("refuses a pattern with a space in it", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "Registration pattern");
    await user.type(screen.getByLabelText("Registration matches"), "N 123");
    await submit(user);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      await screen.findByText("A pattern cannot contain spaces."),
    ).toBeInTheDocument();
  });

  it("edits a ground-speed window in knots with a km/h hint for metric users", async () => {
    const { onSubmit, user } = renderBuilder({ units: "metric" });

    await addCondition(user, "Ground speed");
    await user.type(screen.getByLabelText("At most (kt)"), "100");

    expect(await screen.findByText(/≈ 185\.2 km\/h/)).toBeInTheDocument();

    await submit(user);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        conditions: { version: 2, max_ground_speed_kt: 100 },
      }),
    );
  });

  it("states vertical-rate bounds in ft/min, sign included", async () => {
    const { onSubmit, user } = renderBuilder({ units: "metric" });

    await addCondition(user, "Vertical rate");
    await user.type(screen.getByLabelText("At or below (ft/min)"), "-1000");
    expect(await screen.findByText(/≈ -5\.1 m\/s/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("At or above (ft/min)"), "-30000");
    await submit(user);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      await screen.findByText(
        "Vertical rates must be between -20000 and 20000 ft/min (negative is descending).",
      ),
    ).toBeInTheDocument();
  });

  it("composes an area from the keyboard fallback", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "Inside an area");
    expect(screen.getByText(/0 of 64 vertices/)).toBeInTheDocument();

    await user.type(
      screen.getByLabelText("Vertices (longitude, latitude)"),
      "-2, 50{Enter}-1, 50{Enter}-1, 51",
    );
    expect(screen.getByText(/3 of 64 vertices/)).toBeInTheDocument();

    await submit(user);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        conditions: {
          version: 2,
          within_area: {
            type: "Polygon",
            coordinates: [
              [
                [-2, 50],
                [-1, 50],
                [-1, 51],
                [-2, 50],
              ],
            ],
          },
        },
      }),
    );
  });

  it("refuses a self-crossing area and says which edges cross", async () => {
    const { onSubmit, user } = renderBuilder();

    await addCondition(user, "Inside an area");
    await user.type(
      screen.getByLabelText("Vertices (longitude, latitude)"),
      "0, 0{Enter}2, 2{Enter}2, 0{Enter}0, 2",
    );
    await submit(user);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/edge 1 crosses edge 3/),
    ).toBeInTheDocument();
  });

  it("loads a saved v2 rule and round-trips it untouched", async () => {
    const conditions = {
      version: 2 as const,
      squawk_in: ["7000"],
      callsign_glob: "RCH*",
      min_vertical_rate_fpm: 500,
      within_area: {
        type: "Polygon" as const,
        coordinates: [
          [
            [-2, 50],
            [-1, 50],
            [-1, 51],
            [-2, 50],
          ] as [number, number][],
        ],
      },
    };
    const { onSubmit, user } = renderBuilder({
      rule: alertRule({ id: 9, name: "Reach", conditions }),
    });

    expect(screen.getByLabelText("Vertices (longitude, latitude)")).toHaveValue(
      "-2, 50\n-1, 50\n-1, 51",
    );
    expect(screen.getByLabelText("Callsign matches")).toHaveValue("RCH*");

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ conditions }),
    );
  });
});
