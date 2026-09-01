/**
 * Reconnect backoff for the live socket.
 *
 * `docs/API.md` §4.5 says clients reconnect "with backoff" and leaves the curve
 * to the client; the server side of the same rule is what makes the curve
 * matter. A FlightSite backend drops a slow or unresponsive client with close
 * code 1013 and expects it back (`backend/src/flightsite/api/ws.py`), and a
 * Raspberry Pi that has just shed a client because it fell behind is exactly
 * the machine that must not then be hit by an unthrottled reconnect storm from
 * every open browser tab.
 *
 * Hence *equal jitter*: half the exponential delay is fixed and half is random.
 * Full jitter would let an unlucky draw retry after a couple of milliseconds;
 * no jitter would let N tabs that lost the same backend retry in lockstep
 * forever. Equal jitter keeps a floor under the retry rate and still
 * decorrelates clients.
 */

export interface BackoffOptions {
  /** Delay for the first retry, before jitter. */
  baseDelayMs: number;
  /** Ceiling the exponential curve is clamped to, before jitter. */
  maxDelayMs: number;
}

/** Half a second, doubling to a thirty-second ceiling. A backend restart is
 * usually back inside two or three attempts, and a backend that is genuinely
 * gone is retried twice a minute rather than continuously. */
export const DEFAULT_BACKOFF: BackoffOptions = {
  baseDelayMs: 500,
  maxDelayMs: 30_000,
};

/**
 * Delay before retry number `attempt` (1-based: the first reconnect is 1).
 *
 * @param attempt - consecutive failed connection attempts so far, ≥ 1.
 * @param options - the curve's base and ceiling.
 * @param random - source of the jitter draw in `[0, 1)`; injected so tests can
 *   pin both ends of the range instead of asserting on a distribution.
 */
export function backoffDelayMs(
  attempt: number,
  options: BackoffOptions = DEFAULT_BACKOFF,
  random: () => number = Math.random,
): number {
  const steps = Math.max(0, Math.floor(attempt) - 1);
  // `2 ** steps` overflows to Infinity long before it matters, and Infinity
  // clamps to maxDelayMs like any other over-large value, so no guard is
  // needed on the exponent itself.
  const exponential = Math.min(
    options.maxDelayMs,
    options.baseDelayMs * 2 ** steps,
  );
  return Math.round(exponential / 2 + random() * (exponential / 2));
}
