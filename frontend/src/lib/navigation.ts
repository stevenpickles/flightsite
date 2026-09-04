/**
 * A one-slot bridge from non-React code to the router (ADR-0015, issue #105).
 *
 * The router lives in React — `useNavigate` is a hook — while the code that
 * sometimes needs to move the tab does not: a browser notification's click
 * handler runs long after any render, from a module the socket frame handler
 * called. Before ADR-0015 that was fine, because the socket delivering the
 * alert belonged to the Live Map and so the tab was already there. Now that
 * the shell owns the socket, an alert can be clicked from any route, and
 * SPEC §48's "clicking should open/select the aircraft" needs a way home.
 *
 * `components/shell/AppShell` registers the router's `navigate` while it is
 * mounted and clears it on unmount. Anything else calls {@link navigateTo}.
 * With nothing registered — the setup wizard, or a test that renders a
 * component without the shell — the call is a silent no-op: there is no app
 * chrome to navigate within, so there is nowhere to go.
 */

type Navigate = (path: string) => void;

let navigator: Navigate | null = null;

/** Installs (or, with `null`, removes) the function {@link navigateTo} uses. */
export function registerNavigator(fn: Navigate | null): void {
  navigator = fn;
}

/**
 * Client-side navigation to an app path; a no-op when no shell is mounted,
 * and a no-op when the tab is already there (the shell checks).
 */
export function navigateTo(path: string): void {
  navigator?.(path);
}
