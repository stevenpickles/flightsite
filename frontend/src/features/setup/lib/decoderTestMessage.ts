import type { ConnectionTestResult } from "@/lib/api/decoder";

const ERROR_LABELS: Record<string, string> = {
  unreachable: "Unreachable",
  http_error: "Endpoint returned an error",
  invalid_document: "Response was not a decoder aircraft document",
};

/** Renders a successful `ConnectionTestResult` as one readable sentence,
 * e.g. "Connected — found readsb, 37 aircraft (24 with positions).". */
export function describeConnectionSuccess(
  result: ConnectionTestResult,
): string {
  const flavor =
    result.flavor && result.flavor !== "unknown" ? result.flavor : "a decoder";
  const aircraft = result.aircraft_count ?? 0;
  const positioned = result.positioned_count ?? 0;
  return `Connected — found ${flavor}, ${aircraft} aircraft (${positioned} with positions).`;
}

/** Renders a failed `ConnectionTestResult` using the failure-kind label
 * that maps to a remedy (see `ConnectionTestError` in
 * `backend/src/flightsite/ingest/connection_test.py`), plus the backend's
 * own detail message when it has one. */
export function describeConnectionFailure(
  result: ConnectionTestResult,
): string {
  const label = result.error
    ? (ERROR_LABELS[result.error] ?? result.error)
    : "Connection failed";
  return result.detail ? `${label}: ${result.detail}` : label;
}
