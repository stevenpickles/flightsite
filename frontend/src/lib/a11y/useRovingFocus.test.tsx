/**
 * Unit coverage for the roving-focus keyboard contract (roadmap slice 048).
 *
 * These assert the behavior that the E2E axe sweep structurally cannot see:
 * axe verifies that `role="tab"`/`role="radio"` and their names exist, not
 * that the arrow keys those roles promise actually move focus and selection.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";

import { useRovingFocus } from "@/lib/a11y/useRovingFocus";

const OPTIONS = ["One", "Two", "Three"] as const;

function RadioGroup({
  orientation = "horizontal",
}: {
  orientation?: "horizontal" | "vertical" | "both";
}) {
  const [selected, setSelected] = useState<string>(OPTIONS[0]);
  const groupRef = useRef<HTMLDivElement>(null);
  const onKeyDown = useRovingFocus(groupRef, {
    itemRole: "radio",
    orientation,
  });

  return (
    <div
      role="radiogroup"
      aria-label="Example"
      ref={groupRef}
      onKeyDown={onKeyDown}
    >
      {OPTIONS.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={option === selected}
          tabIndex={option === selected ? 0 : -1}
          onClick={() => setSelected(option)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

describe("useRovingFocus", () => {
  it("moves focus AND selection to the next option on the forward arrow", async () => {
    const user = userEvent.setup();
    render(<RadioGroup />);

    const one = screen.getByRole("radio", { name: "One" });
    one.focus();
    expect(one).toHaveFocus();

    await user.keyboard("{ArrowRight}");

    const two = screen.getByRole("radio", { name: "Two" });
    expect(two).toHaveFocus();
    // Selection follows focus — required behavior for a radiogroup, not
    // merely focus movement.
    expect(two).toHaveAttribute("aria-checked", "true");
    expect(one).toHaveAttribute("aria-checked", "false");
  });

  it("moves backwards, and wraps in both directions", async () => {
    const user = userEvent.setup();
    render(<RadioGroup />);

    screen.getByRole("radio", { name: "One" }).focus();

    // Backwards from the first option wraps to the last.
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: "Three" })).toHaveFocus();

    // Forwards from the last wraps back to the first.
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "One" })).toHaveFocus();
  });

  it("supports Home and End", async () => {
    const user = userEvent.setup();
    render(<RadioGroup />);

    screen.getByRole("radio", { name: "One" }).focus();

    await user.keyboard("{End}");
    expect(screen.getByRole("radio", { name: "Three" })).toHaveFocus();

    await user.keyboard("{Home}");
    expect(screen.getByRole("radio", { name: "One" })).toHaveFocus();
  });

  it("ignores the cross-axis arrows for a single-orientation group", async () => {
    const user = userEvent.setup();
    render(<RadioGroup orientation="horizontal" />);

    const one = screen.getByRole("radio", { name: "One" });
    one.focus();

    // A horizontal group must leave ArrowDown alone so it still scrolls the
    // page rather than silently hijacking it.
    await user.keyboard("{ArrowDown}");
    expect(one).toHaveFocus();
    expect(one).toHaveAttribute("aria-checked", "true");
  });

  it("honours a vertical orientation", async () => {
    const user = userEvent.setup();
    render(<RadioGroup orientation="vertical" />);

    screen.getByRole("radio", { name: "One" }).focus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("radio", { name: "Two" })).toHaveFocus();
  });

  it("skips disabled options", async () => {
    function WithDisabled() {
      const groupRef = useRef<HTMLDivElement>(null);
      const onKeyDown = useRovingFocus(groupRef, { itemRole: "radio" });
      return (
        <div
          role="radiogroup"
          aria-label="Example"
          ref={groupRef}
          onKeyDown={onKeyDown}
        >
          <button type="button" role="radio" aria-checked tabIndex={0}>
            One
          </button>
          <button type="button" role="radio" aria-checked={false} disabled>
            Two
          </button>
          <button type="button" role="radio" aria-checked={false} tabIndex={-1}>
            Three
          </button>
        </div>
      );
    }
    const user = userEvent.setup();
    render(<WithDisabled />);

    screen.getByRole("radio", { name: "One" }).focus();
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("radio", { name: "Three" })).toHaveFocus();
  });
});
