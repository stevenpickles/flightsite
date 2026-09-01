import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlaceholderPage } from "./PlaceholderPage";

describe("PlaceholderPage", () => {
  it("renders the section title as a heading and the description as text", () => {
    render(<PlaceholderPage title="Example Section" description="One line." />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Example Section" }),
    ).toBeInTheDocument();
    expect(screen.getByText("One line.")).toBeInTheDocument();
  });
});
