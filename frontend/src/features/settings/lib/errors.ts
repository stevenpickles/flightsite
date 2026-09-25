/**
 * Maps a failed `PUT /api/internal/config` onto the Settings form: a
 * per-field message keyed by dotted path (matching `ConfigPatch`'s own
 * shape, e.g. `"location.latitude"`, `"retention.high_res_metric_days"`),
 * plus a general (non-field) message for anything else.
 *
 * `store.apply_update` validates the merged document directly against
 * `Settings` (`backend/src/flightsite/config/loader.py`), not through
 * FastAPI's request-body model, so each Pydantic error's `loc` is the bare
 * field path (`["location", "latitude"]`) with no leading `"body"` segment
 * — see `_safe_errors` in `backend/src/flightsite/api/internal.py`.
 */
import { ApiError } from "@/lib/api/client";

/** Every dotted field path a failed save produced a message for. */
export type FieldErrors = Record<string, string>;

interface RawErrorEntry {
  loc: unknown[];
  msg: string;
}

function isRawErrorEntry(value: unknown): value is RawErrorEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { loc?: unknown }).loc) &&
    typeof (value as { msg?: unknown }).msg === "string"
  );
}

/** Field-level messages from a rejected save, keyed by dotted path. Empty
 * for anything that isn't the `{loc, msg, type}[]` validation-error shape
 * (a plain-string `ConfigError` detail, a network failure, etc.) — those
 * are surfaced instead by {@link generalErrorMessage}. */
export function fieldErrorsFrom(error: unknown): FieldErrors {
  if (!(error instanceof ApiError) || !Array.isArray(error.detail)) {
    return {};
  }
  const errors: FieldErrors = {};
  for (const entry of error.detail) {
    if (!isRawErrorEntry(entry)) {
      continue;
    }
    const path = entry.loc
      .filter((part): part is string | number => typeof part !== "object")
      .join(".");
    if (path.length > 0) {
      errors[path] = entry.msg;
    }
  }
  return errors;
}

/** A field's message plus whether it should gate Save.
 *
 * `blocking` is only ever true for a client-side check: a server rejection
 * is real information ("the backend said no") but never a reason to disable
 * the one control that could fix it. Without this split, a section that
 * folded a server message into the same variable that gates Save (R4-02,
 * `docs/reviews/2026-09-20-site-review.md`) left six of nine Settings
 * sections permanently unsavable after one 422 — `mutation.error` is only
 * cleared by the next `mutate()`, which a disabled button makes
 * impossible. */
export interface FieldMessage {
  message: string | null;
  blocking: boolean;
}

/**
 * Combines a client-side validator's result with a server-side field
 * message for the same field, the way `EnrichmentSection.tsx` first worked
 * out by hand (`budgetBoundsError` / `budgetError`, see its comment): the
 * client error wins when present (it is why Save is disabled), otherwise the
 * server's message is shown but never blocks — a save the user can retry the
 * moment they change anything, rather than a dead end until a page reload.
 */
export function fieldMessage(
  clientError: string | null,
  serverError: string | null | undefined,
): FieldMessage {
  if (clientError !== null) {
    return { message: clientError, blocking: true };
  }
  if (serverError) {
    return { message: serverError, blocking: false };
  }
  return { message: null, blocking: false };
}

/** A single readable message for anything a `FieldErrors` map didn't
 * already explain next to a field — a plain-string `ConfigError` detail
 * (e.g. an unknown key), a network failure, or the validation errors
 * themselves when none carried a usable `loc`. `null` once every problem
 * is already shown inline next to its field. */
export function generalErrorMessage(
  error: unknown,
  fieldErrors: FieldErrors,
): string | null {
  if (error == null) {
    return null;
  }
  if (error instanceof ApiError && Array.isArray(error.detail)) {
    return Object.keys(fieldErrors).length > 0 ? null : error.message;
  }
  return error instanceof Error ? error.message : "Could not save changes.";
}
