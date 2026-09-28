import { describe, expect, it } from "vitest";

import { isTypingTarget } from "./isTypingTarget";

describe("isTypingTarget", () => {
  it("is true for input, textarea and select elements", () => {
    expect(isTypingTarget(document.createElement("input"))).toBe(true);
    expect(isTypingTarget(document.createElement("textarea"))).toBe(true);
    expect(isTypingTarget(document.createElement("select"))).toBe(true);
  });

  it("is true for a contenteditable element", () => {
    // jsdom does not compute `isContentEditable` from the `contentEditable`
    // attribute (a documented jsdom gap), so the property is set directly —
    // exactly what a real browser would report for one.
    const div = document.createElement("div");
    Object.defineProperty(div, "isContentEditable", { value: true });
    expect(isTypingTarget(div)).toBe(true);
  });

  it("is false for an ordinary element", () => {
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
    expect(isTypingTarget(document.createElement("div"))).toBe(false);
  });

  it("is false for null or a non-element target", () => {
    expect(isTypingTarget(null)).toBe(false);
    expect(isTypingTarget(window)).toBe(false);
  });
});
