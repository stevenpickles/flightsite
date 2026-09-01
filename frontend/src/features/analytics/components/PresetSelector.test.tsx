import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PresetSelector } from "@/features/analytics/components/PresetSelector";

describe("PresetSelector", () => {
  it("renders all five presets with the active one checked", () => {
    render(<PresetSelector preset="30d" onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: "30 days" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: "Today" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("radio", { name: "7 days" })).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "This year" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Since T0" })).toBeInTheDocument();
  });

  it("calls onChange with the clicked preset", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PresetSelector preset="today" onChange={onChange} />);

    await user.click(screen.getByRole("radio", { name: "Since T0" }));

    expect(onChange).toHaveBeenCalledWith("t0");
  });
});
