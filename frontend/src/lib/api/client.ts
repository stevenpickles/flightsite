/**
 * Shared fetch helper for the internal API (`/api/internal/*`, docs/API.md
 * §5). It is unversioned and unsupported outside this frontend, but its
 * payload shapes are stable within a running backend, so every consumer
 * goes through one small helper that parses JSON and turns a non-2xx
 * response into a typed, readable error instead of every call site
 * re-deriving one.
 */

/** Thrown for any non-2xx response from the internal API. `detail` carries
 * FastAPI's raw error body (`{"detail": ...}`) — a string for a plain
 * `HTTPException`, or a list of `{loc, msg, type}` objects for a validation
 * error (see `_safe_errors` in `backend/src/flightsite/api/internal.py`). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(describeDetail(detail, status));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface ValidationErrorEntry {
  loc: unknown[];
  msg: string;
  type: string;
}

function isValidationErrorEntry(value: unknown): value is ValidationErrorEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    "msg" in value &&
    typeof (value as { msg: unknown }).msg === "string"
  );
}

function describeDetail(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim().length > 0) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .filter(isValidationErrorEntry)
      .map((entry) => entry.msg);
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }
  return `Request failed with status ${status}`;
}

async function parseJsonBody<T>(response: Response): Promise<T> {
  const text = await response.text();
  return (text.length > 0 ? JSON.parse(text) : undefined) as T;
}

/** Performs a fetch against the internal API and returns the parsed JSON
 * body, throwing {@link ApiError} for any non-2xx response. Callers pass a
 * path already rooted at `/api/internal` — the Vite dev-server proxy (or
 * the production reverse proxy) is what makes that path reach the backend. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await parseJsonBody<{ detail?: unknown }>(response);
      detail = body?.detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(response.status, detail);
  }
  return parseJsonBody<T>(response);
}
