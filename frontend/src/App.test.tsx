import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "@/App";

describe("App", () => {
  it("wires providers and the router, rendering the Live Map at the root path", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Live Map" }),
    ).toBeInTheDocument();
  });
});
