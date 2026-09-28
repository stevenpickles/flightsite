/**
 * Registers FlightSite's service worker (`/sw.js`, built from `src/sw/`) and
 * turns its update lifecycle into the "new version available" prompt
 * (roadmap slice 084, issue #227).
 *
 * **When.** Production builds only, never under `npm run dev` or vitest,
 * and only where the browser can run one at all: a service worker needs a
 * secure context, so an install reached over plain `http://` on a LAN
 * address simply runs without one — exactly as it did before this slice.
 * Every failure is caught here: a worker is an enhancement (installability,
 * an offline shell), and nothing it does may keep the app from starting.
 *
 * **Updates.** A new deploy's worker installs in the background and waits.
 * The prompt is offered when one is waiting — found at registration, or
 * when an install finishes later — and accepting it posts
 * `SKIP_WAITING_MESSAGE`; the page reloads on the resulting
 * `controllerchange`, onto the new shell. The worker never activates
 * without that click. A tab that did *not* ask (another open tab, switched
 * by the first) is offered a plain reload instead of being reloaded under
 * the user. Long-lived tabs — a Live Map left on a wall display — also
 * re-check for a new worker hourly, since a tab that never navigates would
 * otherwise never look.
 */

import { useUpdateStore } from "@/lib/pwa/useUpdateStore";
import { SKIP_WAITING_MESSAGE } from "@/sw/messages";

export const SERVICE_WORKER_URL = "/sw.js";

/** How often an open tab asks the server whether `sw.js` has changed. */
export const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000;

export interface ServiceWorkerEnvironment {
  production: boolean;
  mode: string;
  supported: boolean;
  secureContext: boolean;
}

export function currentServiceWorkerEnvironment(): ServiceWorkerEnvironment {
  return {
    production: import.meta.env.PROD,
    mode: import.meta.env.MODE,
    supported: typeof navigator !== "undefined" && "serviceWorker" in navigator,
    secureContext:
      typeof window !== "undefined" && window.isSecureContext === true,
  };
}

export function shouldRegisterServiceWorker(
  env: ServiceWorkerEnvironment,
): boolean {
  return (
    env.production && env.mode !== "test" && env.supported && env.secureContext
  );
}

export interface RegisterOptions {
  env?: ServiceWorkerEnvironment;
  container?: ServiceWorkerContainer;
  reload?: () => void;
}

/**
 * Registers the worker and wires the update prompt. Resolves to the
 * registration, or `null` when registration is skipped or fails — it never
 * rejects.
 */
export async function registerServiceWorker(
  options: RegisterOptions = {},
): Promise<ServiceWorkerRegistration | null> {
  try {
    const env = options.env ?? currentServiceWorkerEnvironment();
    if (!shouldRegisterServiceWorker(env)) {
      return null;
    }
    const container = options.container ?? navigator.serviceWorker;
    const reload = options.reload ?? (() => window.location.reload());

    const registration = await container.register(SERVICE_WORKER_URL, {
      scope: "/",
    });
    watchForUpdates(registration, container, reload);
    return registration;
  } catch (error) {
    console.warn("FlightSite: service worker registration failed", error);
    return null;
  }
}

function watchForUpdates(
  registration: ServiceWorkerRegistration,
  container: ServiceWorkerContainer,
  reload: () => void,
): void {
  // No controller means this is the first install: there is no older shell
  // on screen to update from, so nothing to prompt about.
  const hadController = container.controller !== null;
  let updateRequested = false;

  function offerWaiting(worker: ServiceWorker) {
    if (container.controller === null) {
      return;
    }
    useUpdateStore.getState().offer(() => {
      updateRequested = true;
      worker.postMessage(SKIP_WAITING_MESSAGE);
    });
  }

  if (registration.waiting) {
    offerWaiting(registration.waiting);
  }

  registration.addEventListener("updatefound", () => {
    const installing = registration.installing;
    if (!installing) {
      return;
    }
    installing.addEventListener("statechange", () => {
      if (installing.state === "installed") {
        offerWaiting(installing);
      }
    });
  });

  container.addEventListener("controllerchange", () => {
    if (updateRequested) {
      reload();
    } else if (hadController) {
      useUpdateStore.getState().offer(reload);
    }
  });

  setInterval(() => {
    registration.update().catch(() => {
      // Offline or the server is restarting; the next check will retry.
    });
  }, UPDATE_CHECK_INTERVAL_MS);
}
