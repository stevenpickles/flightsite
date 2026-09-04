import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RestartRequiredBadge } from "@/features/settings/components/RestartRequiredBadge";
import { SettingsSection } from "@/features/settings/components/SettingsSection";

describe("RestartRequiredBadge", () => {
  it("renders the one wording the page uses", () => {
    render(<RestartRequiredBadge />);
    expect(screen.getByText(/applies on next restart/i)).toBeInTheDocument();
  });

  it("takes an id so a field can describe itself with it", () => {
    render(
      <>
        <label htmlFor="a-field">A field</label>
        <input id="a-field" aria-describedby="a-field-restart" />
        <RestartRequiredBadge id="a-field-restart" />
      </>,
    );

    const describedBy = screen
      .getByLabelText("A field")
      .getAttribute("aria-describedby");
    expect(describedBy).toBe("a-field-restart");
    expect(document.getElementById("a-field-restart")).toHaveTextContent(
      /applies on next restart/i,
    );
  });

  it("gives a section header and a field the identical chip", () => {
    // The point of sharing the component: one page, one phrasing. A
    // hand-rolled inline note is how these two drift apart.
    const { container: sectionContainer } = render(
      <SettingsSection
        id="a-section"
        title="A section"
        description="Whatever."
        restartRequired
      >
        <p>Body.</p>
      </SettingsSection>,
    );
    const { container: fieldContainer } = render(
      <RestartRequiredBadge id="a-field-restart" />,
    );

    const sectionBadge = sectionContainer.querySelector(
      "summary span.rounded-full",
    );
    const fieldBadge = fieldContainer.querySelector("span.rounded-full");
    expect(sectionBadge?.textContent).toBe(fieldBadge?.textContent);
    expect(sectionBadge?.className).toBe(fieldBadge?.className);
  });
});
