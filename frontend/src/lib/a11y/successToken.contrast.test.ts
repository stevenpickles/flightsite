/**
 * Guards the `--success-on-surface` token pair added for R4-01 (slice 076):
 * `text-accent-foreground` — the colour meant to sit *on* `bg-accent` — was
 * being used directly on a plain card, which rendered every healthy status
 * pill and the decoder test's success line as an invisible blank rectangle
 * in both themes (`docs/reviews/2026-09-20-site-review.md` R4-01).
 *
 * This test parses `index.css` itself (no build step, no jsdom
 * `getComputedStyle` — jsdom does not resolve CSS custom properties or
 * cascade layers) and recomputes WCAG contrast from the raw `oklch(...)`
 * values, so a future edit to any of these four numbers fails here instead
 * of shipping another invisible pill.
 */
import { describe, expect, it } from "vitest";

// `?raw` (typed by `vite/client`, already in tsconfig.app.json's `types`) —
// not a filesystem read, so this needs no Node type declarations the rest of
// `src` does not otherwise carry, and Vitest resolves it exactly like Vite
// does in the app.
import css from "@/index.css?raw";

interface Oklch {
  l: number;
  c: number;
  h: number;
}

/** Pulls `--name: oklch(L C H);` out of one `:root { ... }` / `.dark { ... }`
 * block. Deliberately narrow (three bare numbers, no `deg`/`%`/alpha) —
 * every token this file defines is written that way, and a token that
 * stops being that simple should fail this parse rather than be silently
 * skipped. */
function extractToken(css: string, blockSelector: RegExp, name: string): Oklch {
  const blockMatch = blockSelector.exec(css);
  if (!blockMatch) {
    throw new Error(`Could not find a block matching ${blockSelector}`);
  }
  // The selector's block runs from its opening brace to the next top-level
  // closing brace. `index.css`'s `:root` and `.dark` blocks contain no
  // nested `{`, so the first `}` after the match is the block's end.
  const start = blockMatch.index + blockMatch[0].length;
  const end = css.indexOf("\n}", start);
  const block = css.slice(start, end === -1 ? undefined : end);

  const tokenPattern = new RegExp(
    `--${name}:\\s*oklch\\(([-\\d.]+)\\s+([-\\d.]+)\\s+([-\\d.]+)\\)`,
  );
  const tokenMatch = tokenPattern.exec(block);
  if (!tokenMatch) {
    throw new Error(`Could not find --${name} inside the matched block`);
  }
  const [, l, c, h] = tokenMatch;
  return { l: Number(l), c: Number(c), h: Number(h) };
}

/**
 * OKLab -> linear sRGB, the matrix from the CSS Color 4 spec / Björn
 * Ottosson's OKLab reference implementation — the same transform browsers
 * use to resolve `oklch()`.
 */
function oklchToLinearSrgb({ l, c, h }: Oklch): [number, number, number] {
  const hueRad = (h * Math.PI) / 180;
  const a = c * Math.cos(hueRad);
  const b = c * Math.sin(hueRad);

  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;

  const l3 = l_ ** 3;
  const m3 = m_ ** 3;
  const s3 = s_ ** 3;

  const r = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3;
  const g = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3;
  const bl = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3;
  return [r, g, bl];
}

/** WCAG relative luminance from linear-light sRGB. `oklchToLinearSrgb`
 * already returns linear (not gamma-encoded) values, which is exactly what
 * this formula wants — no separate sRGB-to-linear step is needed. Values
 * are clamped to `[0, 1]`: a slightly out-of-gamut chroma (as `oklch()`
 * itself renders it) clips to the nearest displayable channel rather than
 * going negative. */
function relativeLuminance(token: Oklch): number {
  const [r, g, b] = oklchToLinearSrgb(token);
  const clamp = (value: number): number => Math.min(1, Math.max(0, value));
  return 0.2126 * clamp(r) + 0.7152 * clamp(g) + 0.0722 * clamp(b);
}

/** WCAG contrast ratio between two colors, order-independent. */
function contrastRatio(a: Oklch, b: Oklch): number {
  const lumA = relativeLuminance(a);
  const lumB = relativeLuminance(b);
  const lighter = Math.max(lumA, lumB);
  const darker = Math.min(lumA, lumB);
  return (lighter + 0.05) / (darker + 0.05);
}

const AA_TEXT_MINIMUM = 4.5;

describe("--success-on-surface contrast (R4-01)", () => {
  const rootBlock = /:root\s*\{/;
  const darkBlock = /\.dark\s*\{/;

  it("clears WCAG AA (4.5:1) for text on the light-theme card", () => {
    const success = extractToken(css, rootBlock, "success-on-surface");
    const card = extractToken(css, rootBlock, "card");
    expect(contrastRatio(success, card)).toBeGreaterThanOrEqual(
      AA_TEXT_MINIMUM,
    );
  });

  it("clears WCAG AA (4.5:1) for text on the dark-theme card", () => {
    const success = extractToken(css, darkBlock, "success-on-surface");
    const card = extractToken(css, darkBlock, "card");
    expect(contrastRatio(success, card)).toBeGreaterThanOrEqual(
      AA_TEXT_MINIMUM,
    );
  });

  it("also clears AA against the page background in both themes", () => {
    // Belt and braces: `StatusPill` sits on `bg-card`, but the same token is
    // reused directly on `bg-background` (the decoder test's result line is
    // not always inside a card), so both surfaces must hold.
    const lightSuccess = extractToken(css, rootBlock, "success-on-surface");
    const lightBackground = extractToken(css, rootBlock, "background");
    const darkSuccess = extractToken(css, darkBlock, "success-on-surface");
    const darkBackground = extractToken(css, darkBlock, "background");

    expect(contrastRatio(lightSuccess, lightBackground)).toBeGreaterThanOrEqual(
      AA_TEXT_MINIMUM,
    );
    expect(contrastRatio(darkSuccess, darkBackground)).toBeGreaterThanOrEqual(
      AA_TEXT_MINIMUM,
    );
  });
});
