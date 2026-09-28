import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QrCode } from "./QrCode";

describe("QrCode", () => {
  it("renders an SVG image encoding the given value", () => {
    const { container } = render(
      <QrCode value="https://example.com/aircraft/ae1463" />,
    );
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("role", "img");
    expect(svg).toHaveAttribute(
      "aria-label",
      "QR code encoding https://example.com/aircraft/ae1463",
    );
  });

  it("draws at least one dark module — a real code, not an empty square", () => {
    const { container } = render(<QrCode value="https://example.com" />);
    const darkRects = container.querySelectorAll("g[fill='#000'] rect");
    expect(darkRects.length).toBeGreaterThan(0);
  });

  it("produces a different module count for a longer value", () => {
    const short = render(<QrCode value="a" />);
    const shortViewBox = short.container
      .querySelector("svg")
      ?.getAttribute("viewBox");
    short.unmount();

    const long = render(
      <QrCode value={"https://example.com/aircraft/" + "x".repeat(120)} />,
    );
    const longViewBox = long.container
      .querySelector("svg")
      ?.getAttribute("viewBox");

    expect(shortViewBox).not.toEqual(longViewBox);
  });

  it("respects the requested pixel size", () => {
    const { container } = render(
      <QrCode value="https://example.com" size={64} />,
    );
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "64");
    expect(svg).toHaveAttribute("height", "64");
  });
});
