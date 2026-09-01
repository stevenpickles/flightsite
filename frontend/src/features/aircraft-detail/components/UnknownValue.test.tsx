import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";

describe("UnknownValue", () => {
  it("renders the word Unknown", () => {
    render(<UnknownValue />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });
});
