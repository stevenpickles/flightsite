import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FieldError } from "@/features/setup/components/FieldError";

describe("FieldError", () => {
  it("renders nothing when there is no message", () => {
    const { container } = render(<FieldError id="x-error" message={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the message as an alert with the given id", () => {
    render(<FieldError id="x-error" message="Something is wrong" />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Something is wrong");
    expect(alert).toHaveAttribute("id", "x-error");
  });
});
