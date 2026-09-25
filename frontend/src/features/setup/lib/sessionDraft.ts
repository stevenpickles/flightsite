/**
 * Persists the setup wizard's in-progress draft across a browser refresh
 * (R4-15, `docs/reviews/2026-09-20-site-review.md`). Before this, the whole
 * eight-step form lived in `useState` with no URL or storage backing, so a
 * refresh, a crash, or an accidental Back-out of the tab cost the entire
 * wizard — on a first-run install that has entered a site name, coordinates,
 * antenna height and a decoder endpoint.
 *
 * `sessionStorage`, not `localStorage`: the draft belongs to this one
 * setup attempt in this one tab, not to the browser indefinitely — closing
 * the tab and coming back later should start clean, the same way an
 * abandoned form in most apps does. Guarded the way
 * `features/map/basemapPersistence.ts` guards `localStorage`: private
 * browsing, a full quota, or storage disabled by policy must degrade to "no
 * draft persisted", never throw and take the wizard down with it.
 */
import type { WizardDraft } from "@/features/setup/types";

export const WIZARD_SESSION_STORAGE_KEY = "flightsite-setup-wizard-draft";

/** The persisted shape. `stepIndex`/`furthestStepIndex` are plain numbers,
 * not the step id, so `SetupWizardPage`'s existing `stepAt`/array-index
 * logic reads them back with no translation. */
export interface WizardSessionState {
  draft: WizardDraft;
  stepIndex: number;
  furthestStepIndex: number;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Loose structural check — enough to reject garbage (a value from a much
 * older build, or storage tampered with by hand) without hand-validating
 * every one of `WizardDraft`'s ~20 fields. A session that passes this but
 * is missing a field the current build added since is still safe: the
 * caller merges it onto a fresh `draftFromConfig(...)` base rather than
 * trusting it standalone, so a missing field falls back to the server's
 * value instead of reading as `undefined` somewhere deep in a step. */
function isWizardSessionState(value: unknown): value is WizardSessionState {
  return (
    isPlainObject(value) &&
    isPlainObject(value.draft) &&
    typeof value.stepIndex === "number" &&
    typeof value.furthestStepIndex === "number"
  );
}

/** Reads the persisted session, or `null` if there is none, it is
 * unreadable (private browsing, corrupt JSON, wrong shape), or storage
 * itself is unavailable. Never throws. */
export function loadWizardSession(): WizardSessionState | null {
  try {
    const raw = window.sessionStorage.getItem(WIZARD_SESSION_STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    return isWizardSessionState(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Persists the current draft and position. Called on every change once
 * the wizard has finished its own initial seeding — see the "only after
 * `initializedRef.current`" guard in `SetupWizardPage.tsx`, which stops
 * this from immediately overwriting a session the page just restored from.
 * Silently no-ops if storage is unavailable. */
export function saveWizardSession(
  draft: WizardDraft,
  stepIndex: number,
  furthestStepIndex: number,
): void {
  try {
    const state: WizardSessionState = { draft, stepIndex, furthestStepIndex };
    window.sessionStorage.setItem(
      WIZARD_SESSION_STORAGE_KEY,
      JSON.stringify(state),
    );
  } catch {
    // Storage unavailable — the wizard still works for this render, it
    // simply will not survive a refresh.
  }
}

/** Drops the persisted session — called once setup finishes successfully,
 * so the next visit to `/setup` (a deliberate re-run from Settings) starts
 * from the live server config rather than resurfacing an old attempt. */
export function clearWizardSession(): void {
  try {
    window.sessionStorage.removeItem(WIZARD_SESSION_STORAGE_KEY);
  } catch {
    // Nothing to do if storage is unavailable — there is nothing stored to
    // clear either way.
  }
}
