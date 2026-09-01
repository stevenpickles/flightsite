/**
 * A scripted stand-in for the browser `WebSocket`.
 *
 * jsdom ships a real `WebSocket` that would try to open a network connection
 * the moment anything renders the Live Map, so this is installed globally in
 * `src/test/setup.ts` for the same reason the MapLibre mock is: the environment
 * cannot provide the real thing, and a test must not depend on a socket server.
 *
 * It is a *script driver*, not a behavioural mock: tests push exact protocol
 * frames through `emitFrame` and read back exactly what the client sent, so the
 * live-socket tests exercise the real client against the real wire format.
 */

/** One frame as the server would send it (`docs/API.md` §4.1). */
export interface ScriptedFrame {
  type: string;
  seq: number;
  ts?: string;
  data?: unknown;
}

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  /** Every payload the client has sent, in order. */
  readonly sent: string[] = [];
  closed = false;

  onopen: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(payload: string): void {
    this.sent.push(payload);
  }

  close(): void {
    this.closed = true;
  }

  /** Delivers a raw text frame. */
  emitRaw(data: unknown): void {
    this.onmessage?.({ data });
  }

  /** Delivers one §4.1 envelope, JSON-encoded as the server would. */
  emitFrame(frame: ScriptedFrame): void {
    this.emitRaw(
      JSON.stringify({
        ts: "2026-08-31T14:03:22.418Z",
        data: null,
        ...frame,
      }),
    );
  }

  /** Simulates the server (or the network) closing the connection. */
  emitClose(code = 1006): void {
    this.closed = true;
    this.onclose?.({ code });
  }

  emitError(): void {
    this.onerror?.({});
  }
}

/** Clears captured instances between tests. */
export function resetWebSocketMock(): void {
  FakeWebSocket.instances = [];
}

/** The most recently constructed socket. Throws if none exists — a test bug,
 * not a case to guard defensively against. */
export function getLastWebSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) {
    throw new Error("No FakeWebSocket has been constructed yet");
  }
  return socket;
}
