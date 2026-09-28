import { afterEach, describe, expect, it, vi } from "vitest";

import { copyToClipboard } from "./clipboard";

afterEach(() => {
  vi.unstubAllGlobals();
  // `execCommand` is left as jsdom defines it (throws "not implemented")
  // unless a test replaces it — restore that baseline explicitly since
  // some tests stub it on `document` directly rather than via `vi.stubGlobal`.
  Reflect.deleteProperty(document, "execCommand");
});

describe("copyToClipboard", () => {
  it("uses the async Clipboard API when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    const succeeded = await copyToClipboard(
      "https://example.com/aircraft/abc123",
    );
    expect(succeeded).toBe(true);
    expect(writeText).toHaveBeenCalledWith(
      "https://example.com/aircraft/abc123",
    );
  });

  it("falls back to execCommand when the Clipboard API rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    document.execCommand = vi.fn().mockReturnValue(true);

    const succeeded = await copyToClipboard("https://example.com/x");
    expect(succeeded).toBe(true);
    expect(document.execCommand).toHaveBeenCalledWith("copy");
  });

  it("falls back to execCommand when navigator.clipboard is entirely absent", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    document.execCommand = vi.fn().mockReturnValue(true);

    const succeeded = await copyToClipboard("https://example.com/x");
    expect(succeeded).toBe(true);
  });

  it("reports failure when every path fails", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    document.execCommand = vi.fn().mockReturnValue(false);

    const succeeded = await copyToClipboard("https://example.com/x");
    expect(succeeded).toBe(false);
  });

  it("does not leave a stray textarea in the document either way", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    document.execCommand = vi.fn().mockReturnValue(true);

    await copyToClipboard("https://example.com/x");
    expect(document.querySelector("textarea")).toBeNull();
  });
});
