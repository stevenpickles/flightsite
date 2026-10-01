/**
 * The one message the page sends the service worker (roadmap slice 084):
 * "activate now". A waiting worker never activates on its own — it waits
 * for the user to accept the update prompt (`UpdatePrompt`), and only then
 * does `lib/pwa/registerServiceWorker.ts` post this to it.
 */

export const SKIP_WAITING_MESSAGE = { type: "SKIP_WAITING" } as const;

export function isSkipWaitingMessage(data: unknown): boolean {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === SKIP_WAITING_MESSAGE.type
  );
}
