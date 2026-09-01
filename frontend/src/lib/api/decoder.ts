/**
 * Typed client for `POST /api/internal/decoder/test` (docs/API.md §5). The
 * shapes mirror `flightsite.ingest.connection_test.ConnectionTestResult`
 * and its `ConnectionTestError` enum field-for-field, and the request body
 * mirrors `ReceiverSettings` — the same model `PUT /config` validates
 * against, so a candidate endpoint the wizard can test is always one it
 * would also be allowed to save.
 */
import { useMutation, type UseMutationResult } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { ReceiverConfig } from "@/lib/api/config";

/** Mirrors `ConnectionTestError` — why a connection test failed, in terms
 * that map to a user remedy. */
export type ConnectionTestErrorKind =
  "unreachable" | "http_error" | "invalid_document";

/** Best-effort decoder identification — mirrors `DecoderFlavor`. */
export type DecoderFlavor = "readsb" | "dump1090-fa" | "unknown";

/** Mirrors `ConnectionTestResult`. */
export interface ConnectionTestResult {
  ok: boolean;
  url: string;
  elapsed_ms: number;
  error: ConnectionTestErrorKind | null;
  detail: string | null;
  aircraft_count: number | null;
  positioned_count: number | null;
  flavor: DecoderFlavor | null;
  decoder_time: string | null;
}

const DECODER_TEST_PATH = "/api/internal/decoder/test";

/** Probes a candidate decoder endpoint once. Omitting `receiver` tests the
 * currently configured one (the backend's `receiver: ReceiverSettings |
 * None = None` default); nothing is written and the live ingestion loop is
 * untouched either way, so this is safe to call repeatedly from the wizard
 * or a settings form. */
export function testDecoderConnection(
  receiver?: ReceiverConfig,
): Promise<ConnectionTestResult> {
  if (receiver === undefined) {
    return apiFetch<ConnectionTestResult>(DECODER_TEST_PATH, {
      method: "POST",
    });
  }
  return apiFetch<ConnectionTestResult>(DECODER_TEST_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(receiver),
  });
}

export function useTestDecoderConnectionMutation(): UseMutationResult<
  ConnectionTestResult,
  Error,
  ReceiverConfig | undefined
> {
  return useMutation({ mutationFn: testDecoderConnection });
}
