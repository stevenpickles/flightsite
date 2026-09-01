/**
 * Where the composed stack is published, for every e2e suite that drives it.
 *
 * `compose.yaml` maps the frontend container's fixed internal 8080 to a host
 * port that defaults to 8090 and is overridable with FLIGHTSITE_HOST_PORT.
 * Three separate places used to hardcode the host half of that mapping — the
 * flow suite's `baseURL`, the visual suite's capture origin, and a pair of
 * absolute-URL assertions in the first-run spec — so moving the published
 * port meant finding all of them or getting a confusing partial failure.
 * They all read this instead.
 *
 * Deliberately reads the same environment variable compose reads, with the
 * same default, so `FLIGHTSITE_HOST_PORT=9000 npm run e2e` works end to end:
 * `scripts/stack.mjs` passes the host environment through to `docker compose`,
 * which publishes on 9000, and Playwright then looks for it there.
 *
 * Nothing here is imported by the visual *replay* path, which serves
 * `frontend/dist` itself on a fixed port and must stay fixed — see
 * VISUAL_PORT in `visual/support/fixtureContract.ts` for why.
 */

/** Host port `compose.yaml` publishes the frontend container on. */
export const STACK_HOST_PORT = Number(process.env.FLIGHTSITE_HOST_PORT ?? 8090);

/**
 * Origin the composed stack serves on.
 *
 * 127.0.0.1, not localhost: on Linux CI runners Firefox resolves localhost to
 * ::1 while Docker publishes the compose port on IPv4 only, which made every
 * Firefox test fail at its first assertion (page never loaded).
 */
export const STACK_BASE_URL = `http://127.0.0.1:${STACK_HOST_PORT}`;
