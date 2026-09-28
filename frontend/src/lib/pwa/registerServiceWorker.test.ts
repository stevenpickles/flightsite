/**
 * Service worker registration (roadmap slice 084): the production-only
 * guard, that a failure never escapes, and the update lifecycle that feeds
 * `UpdatePrompt` — driven through `EventTarget`-backed fakes of the
 * `ServiceWorkerContainer`/`Registration`/`ServiceWorker` trio, since jsdom
 * has no service worker support at all.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  registerServiceWorker,
  shouldRegisterServiceWorker,
  UPDATE_CHECK_INTERVAL_MS,
  type ServiceWorkerEnvironment,
} from "@/lib/pwa/registerServiceWorker";
import { useUpdateStore } from "@/lib/pwa/useUpdateStore";
import { SKIP_WAITING_MESSAGE } from "@/sw/messages";

const PROD: ServiceWorkerEnvironment = {
  production: true,
  mode: "production",
  supported: true,
  secureContext: true,
};

class FakeWorker extends EventTarget {
  state: ServiceWorkerState = "installing";
  readonly postMessage = vi.fn();

  become(state: ServiceWorkerState) {
    this.state = state;
    this.dispatchEvent(new Event("statechange"));
  }
}

class FakeRegistration extends EventTarget {
  waiting: FakeWorker | null = null;
  installing: FakeWorker | null = null;
  readonly update = vi.fn(async () => undefined);
}

class FakeContainer extends EventTarget {
  controller: object | null;
  readonly registration = new FakeRegistration();
  readonly register = vi.fn(async () => this.registration);

  constructor({ controlled }: { controlled: boolean }) {
    super();
    this.controller = controlled ? {} : null;
  }
}

function asContainer(container: FakeContainer) {
  return container as unknown as ServiceWorkerContainer;
}

beforeEach(() => {
  vi.useFakeTimers();
  useUpdateStore.setState({ apply: null, dismissed: false });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("shouldRegisterServiceWorker", () => {
  it("registers only in a production build, outside tests, where supported and secure", () => {
    expect(shouldRegisterServiceWorker(PROD)).toBe(true);
    expect(shouldRegisterServiceWorker({ ...PROD, production: false })).toBe(
      false,
    );
    expect(shouldRegisterServiceWorker({ ...PROD, mode: "test" })).toBe(false);
    expect(shouldRegisterServiceWorker({ ...PROD, supported: false })).toBe(
      false,
    );
    expect(shouldRegisterServiceWorker({ ...PROD, secureContext: false })).toBe(
      false,
    );
  });

  it("is off in this very test run's own environment", async () => {
    // No `env` override: vitest's `import.meta.env` is a test-mode dev build.
    const container = new FakeContainer({ controlled: false });
    await expect(
      registerServiceWorker({ container: asContainer(container) }),
    ).resolves.toBeNull();
    expect(container.register).not.toHaveBeenCalled();
  });
});

describe("registerServiceWorker", () => {
  it("registers /sw.js at the root scope", async () => {
    const container = new FakeContainer({ controlled: false });
    await registerServiceWorker({
      env: PROD,
      container: asContainer(container),
    });
    expect(container.register).toHaveBeenCalledWith("/sw.js", { scope: "/" });
  });

  it("resolves to null instead of throwing when registration fails", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const container = new FakeContainer({ controlled: false });
    container.register.mockRejectedValueOnce(new Error("SecurityError"));
    await expect(
      registerServiceWorker({ env: PROD, container: asContainer(container) }),
    ).resolves.toBeNull();
  });

  it("offers a worker already waiting, and activates it only on request", async () => {
    const container = new FakeContainer({ controlled: true });
    const waiting = new FakeWorker();
    container.registration.waiting = waiting;
    const reload = vi.fn();

    await registerServiceWorker({
      env: PROD,
      container: asContainer(container),
      reload,
    });
    const apply = useUpdateStore.getState().apply;
    expect(apply).not.toBeNull();
    expect(waiting.postMessage).not.toHaveBeenCalled();

    apply?.();
    expect(waiting.postMessage).toHaveBeenCalledWith(SKIP_WAITING_MESSAGE);
    expect(reload).not.toHaveBeenCalled();

    container.dispatchEvent(new Event("controllerchange"));
    expect(reload).toHaveBeenCalledOnce();
  });

  it("offers a worker that finishes installing later", async () => {
    const container = new FakeContainer({ controlled: true });
    await registerServiceWorker({
      env: PROD,
      container: asContainer(container),
    });
    expect(useUpdateStore.getState().apply).toBeNull();

    const installing = new FakeWorker();
    container.registration.installing = installing;
    container.registration.dispatchEvent(new Event("updatefound"));
    installing.become("installed");

    expect(useUpdateStore.getState().apply).not.toBeNull();
  });

  it("offers nothing on the very first install", async () => {
    const container = new FakeContainer({ controlled: false });
    await registerServiceWorker({
      env: PROD,
      container: asContainer(container),
    });

    const installing = new FakeWorker();
    container.registration.installing = installing;
    container.registration.dispatchEvent(new Event("updatefound"));
    installing.become("installed");

    expect(useUpdateStore.getState().apply).toBeNull();
  });

  it("offers a reload, not a forced one, when another tab switched workers", async () => {
    const container = new FakeContainer({ controlled: true });
    const reload = vi.fn();
    await registerServiceWorker({
      env: PROD,
      container: asContainer(container),
      reload,
    });

    container.dispatchEvent(new Event("controllerchange"));
    expect(reload).not.toHaveBeenCalled();
    useUpdateStore.getState().apply?.();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("re-checks for a new worker hourly", async () => {
    const container = new FakeContainer({ controlled: true });
    await registerServiceWorker({
      env: PROD,
      container: asContainer(container),
    });
    expect(container.registration.update).not.toHaveBeenCalled();
    vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS);
    expect(container.registration.update).toHaveBeenCalledOnce();
  });
});
