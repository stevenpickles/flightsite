/**
 * A stand-in for the browser `Notification` API (roadmap slice 040).
 *
 * Unlike the WebSocket and MapLibre mocks, this one is **not** installed in
 * `src/test/setup.ts`. jsdom implements no `Notification` at all, and that
 * absence is the correct default for the suite: it is exactly the "browser
 * cannot notify" state FlightSite must degrade cleanly into, so every test
 * that does not opt in proves, incidentally, that nothing tries to notify
 * where it cannot. Tests that need the API install it themselves with
 * {@link installNotificationMock} and let `vi.unstubAllGlobals()` remove it.
 *
 * It records rather than simulates: constructed notifications are kept so a
 * test can assert on the exact title, body and tag the dispatcher composed,
 * and `onclick` is invoked by the test rather than by any event plumbing.
 */

import { vi } from "vitest";

export interface FakeNotificationOptions {
  body?: string;
  tag?: string;
}

export class FakeNotification {
  /** Every notification constructed since the last install, in order. */
  static instances: FakeNotification[] = [];
  /** What `Notification.permission` reports. */
  static permission: NotificationPermission = "granted";
  /** What `Notification.requestPermission()` resolves to. */
  static requestPermission = vi.fn<() => Promise<NotificationPermission>>();
  /** When set, the constructor throws it — the "browser refused to
   * construct" path (a platform that disallows non-persistent notifications,
   * for instance). */
  static constructorError: Error | null = null;

  readonly title: string;
  readonly options: FakeNotificationOptions;
  onclick: (() => void) | null = null;
  closed = false;

  constructor(title: string, options: FakeNotificationOptions = {}) {
    if (FakeNotification.constructorError) {
      throw FakeNotification.constructorError;
    }
    this.title = title;
    this.options = options;
    FakeNotification.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }
}

export interface NotificationMockOptions {
  /** The standing permission. Defaults to `"granted"`. */
  permission?: NotificationPermission;
  /** What a request resolves to. Defaults to the standing permission. */
  requestResult?: NotificationPermission;
}

/**
 * Installs {@link FakeNotification} as `globalThis.Notification` and returns
 * it. Also marks the context secure, so a test never accidentally exercises
 * the insecure-origin path it did not ask for.
 */
export function installNotificationMock(
  options: NotificationMockOptions = {},
): typeof FakeNotification {
  const permission = options.permission ?? "granted";
  FakeNotification.instances = [];
  FakeNotification.permission = permission;
  FakeNotification.constructorError = null;
  FakeNotification.requestPermission = vi.fn<
    () => Promise<NotificationPermission>
  >(() => {
    const result = options.requestResult ?? permission;
    FakeNotification.permission = result;
    return Promise.resolve(result);
  });
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("Notification", FakeNotification);
  return FakeNotification;
}

/** The last notification the code under test constructed. */
export function lastNotification(): FakeNotification | undefined {
  return FakeNotification.instances.at(-1);
}
