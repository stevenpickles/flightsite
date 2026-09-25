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
 * error (see `_safe_errors` in `backend/src/flightsite/api/internal.py`).
 * The backend chose this message, so it is safe to show verbatim — contrast
 * {@link NetworkError}, where there is no backend message to show. */
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

/** Thrown when the request never reached a server that answered — `fetch`
 * itself rejected (offline, DNS failure, CORS, the backend process not
 * listening) rather than the backend sending a documented error envelope.
 * Distinct from {@link ApiError} so a raw `TypeError: Failed to fetch`, or
 * an `AbortError`, never reaches a screen: nothing about the browser's
 * exception text is meant for a reader, only for `cause`/devtools.
 * R3-08, R4-19. */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("FlightSite's backend is not responding.", { cause });
    this.name = "NetworkError";
  }
}

/** Human-facing text for anything a fetch against the API can throw:
 * {@link ApiError}'s own (backend-authored) message, {@link NetworkError}'s
 * fixed transport message, or a generic fallback for anything else (a
 * programming error, a thrown non-`Error` value) — never that value's own
 * `.message`, which was never written for a reader. Callers that already
 * have a better, page-specific fallback string should use it instead of
 * this generic one for the non-`ApiError`/`NetworkError` case; this helper
 * exists so *no* page falls through to raw exception text by default. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError) {
    return error.message;
  }
  return "Something went wrong.";
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
 * body, throwing {@link ApiError} for any non-2xx response or
 * {@link NetworkError} if the request never reached a server at all.
 * Callers pass a path already rooted at `/api/internal` — the Vite
 * dev-server proxy (or the production reverse proxy) is what makes that
 * path reach the backend. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (cause) {
    // `fetch` rejects (rather than resolving with a non-ok `Response`) only
    // for transport failures — it never rejects because of a 4xx/5xx. An
    // aborted request (`init.signal`) also lands here; callers that need to
    // tell that apart from a genuine outage can still inspect `cause`.
    throw new NetworkError(cause);
  }
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
