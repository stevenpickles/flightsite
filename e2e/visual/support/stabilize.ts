/**
 * Stabilization primitives for the visual regression suite (roadmap slice
 * 047, SPEC §83, `docs/TEST_STRATEGY.md` §5).
 *
 * A screenshot baseline is only worth having if the same UI produces the
 * same pixels every time. Everything in this file exists to remove one
 * source of run-to-run variation:
 *
 *   theme        — pinned per screenshot, not inherited from a default
 *   clock        — `Date.now()` frozen, so relative timestamps don't tick
 *   motion       — CSS transitions/animations neutralized before first paint
 *   renderer     — the run refuses to proceed off the pinned container
 *
 * The two remaining sources — API responses and the live WebSocket — are
 * handled in `replay.ts`, and basemap tiles are blocked by the shared
 * fixture. Between them, a visual run touches no clock, no network, and no
 * backend.
 */

import type { Page } from "@playwright/test";

import { FIXTURE_MANIFEST } from "./fixtureStore";

/** The two themes every view is captured in (SPEC §83: "dark and light"). */
export const VISUAL_THEMES = ["dark", "light"] as const;
export type VisualTheme = (typeof VISUAL_THEMES)[number];

/** Mirrors `THEME_STORAGE_KEY` in `frontend/src/lib/theme.ts`. */
const THEME_STORAGE_KEY = "flightsite-ui-theme";

/**
 * Pins the color theme for a page, before anything renders.
 *
 * `frontend/index.html` runs a blocking inline script in `<head>` that reads
 * this exact localStorage key and toggles `.dark` on `<html>` before first
 * paint (the app's own FOUC guard), and `useUiStore` initializes from the
 * same value. Seeding storage in an init script therefore sets the theme
 * through the app's real mechanism — no clicking the toggle, no waiting for
 * a re-render, and no intermediate frame in the wrong theme that a
 * screenshot might catch.
 *
 * Must be called before `page.goto`.
 */
export async function pinTheme(page: Page, theme: VisualTheme): Promise<void> {
  await page.addInitScript(
    ([key, value]) => {
      try {
        window.localStorage.setItem(key!, value!);
      } catch {
        // Storage unavailable: the app falls back to its dark default, and
        // the light-theme screenshots would fail loudly rather than
        // silently baseline the wrong thing.
      }
    },
    [THEME_STORAGE_KEY, theme] as const,
  );
}

/**
 * Freezes `Date.now()` / `new Date()` at the instant the fixtures were
 * captured, so every relative timestamp in the UI renders identically on
 * every run.
 *
 * This matters more than it sounds: `useRelativeAge`
 * (`frontend/src/features/aircraft-detail/lib/useRelativeAge.ts`) recomputes
 * a "last seen" string from `Date.now()` on a 1 Hz interval, so the aircraft
 * detail view would otherwise show a different age in every screenshot —
 * a guaranteed-failing baseline.
 *
 * `setFixedTime`, not `install`: fixing the clock leaves `requestAnimationFrame`
 * and real timers running normally, so ECharts' entry animation and any CSS
 * transition still run to completion on their own. Faking timers wholesale
 * would freeze those mid-flight instead, and `toHaveScreenshot` already
 * waits for the page to stop changing before it compares. Freeze the
 * *readings*, let the *rendering* finish.
 */
export async function freezeClock(page: Page): Promise<void> {
  await page.clock.setFixedTime(new Date(FIXTURE_MANIFEST.frozenClock));
}

/**
 * Neutralizes motion before first paint.
 *
 * `toHaveScreenshot({ animations: "disabled" })` already freezes CSS
 * animations and finishes transitions at capture time, but it acts at the
 * moment of the screenshot. This stylesheet acts from the first frame, which
 * removes a subtler problem: a transition still in flight can leave a
 * committed layout or a compositor layer that rounds a pixel differently
 * than the settled state. Zeroing durations up front means the page reaches
 * its final appearance immediately and stays there.
 *
 * `prefers-reduced-motion` is set as well, so any component that honors it
 * takes its reduced-motion path — the same path a reduced-motion user sees.
 */
export async function disableMotion(page: Page): Promise<void> {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    const css = `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
        scroll-behavior: auto !important;
      }
      /* toHaveScreenshot hides the caret at capture time; this also stops a
         focused field painting a blinking outline before then. */
      * { caret-color: transparent !important; }
    `;
    const inject = () => {
      const style = document.createElement("style");
      style.setAttribute("data-flightsite-visual", "no-motion");
      style.textContent = css;
      document.head.appendChild(style);
    };
    if (document.head) {
      inject();
    } else {
      document.addEventListener("DOMContentLoaded", inject, { once: true });
    }
  });
}

/**
 * Refuses to run anywhere but the pinned Linux container.
 *
 * Screenshot baselines are a function of the font stack, the font renderer
 * (FreeType version and hinting/antialiasing settings), and the graphics
 * stack — none of which match between Windows, macOS, a bare Ubuntu runner,
 * and the Playwright image. `docs/TEST_STRATEGY.md` §5 pins font rendering
 * "by running in the CI container image"; this is the enforcement.
 *
 * Without this guard the failure mode is silent and expensive rather than
 * loud: `snapshotPathTemplate` carries no `{platform}` (see
 * `playwright.visual.config.ts` for why), so a developer running the suite
 * directly on Windows would compare Windows pixels against Linux baselines
 * and see every test fail — or, with `--update-snapshots`, would overwrite
 * the committed Linux baselines with Windows ones and push a PR that can
 * never pass CI. Stopping the run with the correct command in the message
 * is the whole point.
 *
 * `FLIGHTSITE_VISUAL_ALLOW_HOST=1` overrides, for debugging the harness
 * itself (e.g. checking a selector resolves). Never use it to write
 * baselines — the guard is what keeps the committed set single-platform.
 */
export function assertPinnedRenderer(): void {
  if (process.env.FLIGHTSITE_VISUAL_ALLOW_HOST === "1") {
    console.warn(
      "[visual] FLIGHTSITE_VISUAL_ALLOW_HOST=1 — renderer guard bypassed. " +
        "Screenshots taken now are NOT comparable to the committed baselines; " +
        "do not commit anything --update-snapshots writes in this mode.",
    );
    return;
  }

  if (process.platform !== "linux" || !process.env.FLIGHTSITE_VISUAL_CONTAINER) {
    throw new Error(
      [
        "The visual regression suite must run inside the pinned Playwright container,",
        `not directly on this host (platform: ${process.platform}).`,
        "Screenshot baselines depend on the container's font rendering, so a host run",
        "would compare — or overwrite — the committed baselines with incomparable pixels.",
        "",
        "Run it the supported way, from e2e/:",
        "",
        "  npm run visual            # compare against the committed baselines",
        "  npm run visual:update     # regenerate the baselines after an intended UI change",
        "",
        "Both wrap the suite in mcr.microsoft.com/playwright — the same image CI uses.",
        "See docs/DEVELOPMENT.md, \"Visual regression suite\".",
      ].join("\n"),
    );
  }
}
