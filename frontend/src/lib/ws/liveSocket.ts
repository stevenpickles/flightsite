/**
 * The live-picture WebSocket client (`/api/v1/ws/live`).
 *
 * Implements the client half of the protocol documented in
 * `backend/src/flightsite/api/ws.py` and `docs/API.md` §4:
 *
 * - **Snapshot then deltas.** Every connection opens with a `snapshot` that
 *   replaces the whole picture; `delta` frames then arrive about once a second
 *   and are applied in the documented order — `removed`, then `stale`, then
 *   `updated`. That order lives in the store's `applyDelta`, which is where the
 *   picture actually changes; this client's job is to hand it whole frames.
 * - **Application-level keepalive.** The server sends a `ping` *frame* (not a
 *   transport ping) every 30 s and disconnects a client that has sent nothing
 *   across two of them. Answering with `{"type":"pong"}` is mandatory, and it
 *   is the only thing this client ever sends.
 * - **Reconnect is the only resync.** There is no delta replay. Any close —
 *   1013 "try again later" from the server's slow-consumer guard, a proxy
 *   timeout, a laptop lid — is handled identically: back off, reconnect, take
 *   the fresh snapshot.
 * - **`seq` gaps.** `seq` is per connection and strictly increments by one.
 *   The server never leaves a gap (it disconnects a client it cannot deliver to
 *   in order instead), so a gap observed here means frames were lost between
 *   the two ends. The client's whole picture is then suspect, and the documented
 *   recovery is the same one: force a reconnect and resync from the snapshot.
 *
 * Everything that touches the environment — the socket constructor, the jitter
 * source, the location the URL is derived from — is injectable, so the tests
 * drive real protocol sequences through a scripted socket rather than asserting
 * on mocks of this module.
 */

import type { BackoffOptions } from "@/lib/ws/backoff";
import { backoffDelayMs, DEFAULT_BACKOFF } from "@/lib/ws/backoff";
import type { DeltaData, SnapshotData } from "@/lib/ws/protocol";
import {
  asDeltaData,
  asSnapshotData,
  LIVE_WS_PATH,
  parseServerFrame,
  PONG_MESSAGE,
} from "@/lib/ws/protocol";

/**
 * Connection state as the UI needs to describe it.
 *
 * `connecting` is the first attempt only; once a connection has ever produced
 * a snapshot, every later outage is `reconnecting`. The distinction is what
 * lets the status chip stay quiet on first load and speak up when a working
 * stream drops.
 */
export type ConnectionStatus = "connecting" | "live" | "reconnecting";

/** The slice of the `WebSocket` API this client uses. Narrowing it to these
 * five members is what makes a scripted test double a legitimate stand-in
 * rather than a partial mock of a browser global. */
export interface LiveSocketLike {
  onopen: ((event: unknown) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  send(payload: string): void;
  close(): void;
}

export interface LiveSocketHandlers {
  /** A `snapshot` frame: replaces the client's entire picture (§4.2). */
  onSnapshot: (data: SnapshotData) => void;
  /** A `delta` frame: one second's batch (§4.3). */
  onDelta: (data: DeltaData) => void;
  /** Connection state changed. Called only on a genuine transition. */
  onStatus: (status: ConnectionStatus) => void;
}

export interface LiveSocketOptions extends Partial<LiveSocketHandlers> {
  /** Absolute socket URL. Defaults to {@link liveSocketUrl} over the current
   * origin, which is what routes the connection through the same proxy the
   * REST calls use. */
  url?: string;
  /** Constructs the underlying socket. Defaults to the browser `WebSocket`. */
  socketFactory?: (url: string) => LiveSocketLike;
  backoff?: BackoffOptions;
  /** Jitter source, injected for deterministic tests. */
  random?: () => number;
}

/**
 * The live socket's URL for a page served from `origin`.
 *
 * Derived from the document's own location rather than configured, so the
 * socket reaches the backend through whatever proxies the app itself came
 * through — the Vite dev-server proxy in development, the deployment's reverse
 * proxy in production. `https` pages must use `wss` or the browser blocks the
 * connection as mixed content, which is the only transformation needed.
 */
export function liveSocketUrl(
  location: { protocol: string; host: string } = window.location,
): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}${LIVE_WS_PATH}`;
}

function defaultSocketFactory(url: string): LiveSocketLike {
  return new WebSocket(url) as unknown as LiveSocketLike;
}

export class LiveSocket {
  private readonly handlers: LiveSocketHandlers;
  private readonly url: string;
  private readonly socketFactory: (url: string) => LiveSocketLike;
  private readonly backoff: BackoffOptions;
  private readonly random: () => number;

  private socket: LiveSocketLike | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private lastSeq: number | null = null;
  private started = false;
  private everConnected = false;
  private status: ConnectionStatus = "connecting";

  constructor(options: LiveSocketOptions = {}) {
    this.handlers = {
      onSnapshot: options.onSnapshot ?? (() => {}),
      onDelta: options.onDelta ?? (() => {}),
      onStatus: options.onStatus ?? (() => {}),
    };
    this.url = options.url ?? liveSocketUrl();
    this.socketFactory = options.socketFactory ?? defaultSocketFactory;
    this.backoff = options.backoff ?? DEFAULT_BACKOFF;
    this.random = options.random ?? Math.random;
  }

  /** Current connection state; also pushed through `onStatus`. */
  get connectionStatus(): ConnectionStatus {
    return this.status;
  }

  /** Opens the connection. Idempotent — a second call while running is a no-op. */
  start(): void {
    if (this.started) {
      return;
    }
    this.started = true;
    // Emitted unconditionally rather than through `emitStatus`, so a caller
    // that only listens to the callback still learns the initial state.
    this.status = "connecting";
    this.handlers.onStatus("connecting");
    this.open();
  }

  /** Closes the connection and cancels any pending retry. After `stop()` the
   * instance stays stopped; the caller creates a new one to reconnect. */
  stop(): void {
    this.started = false;
    this.clearRetry();
    this.detach();
  }

  private open(): void {
    this.lastSeq = null;
    const socket = this.socketFactory(this.url);
    this.socket = socket;
    // `onopen` is deliberately left unhooked: a socket that opens and is
    // dropped before its snapshot has not delivered a live picture, and
    // flipping the chip to "live" for that moment would be a lie. The
    // snapshot is what marks the stream healthy (see `handleMessage`).
    socket.onmessage = (event) => {
      this.handleMessage(event.data);
    };
    socket.onerror = () => {
      this.handleDisconnect();
    };
    socket.onclose = () => {
      this.handleDisconnect();
    };
  }

  private handleMessage(raw: unknown): void {
    const frame = parseServerFrame(raw);
    if (!frame) {
      return;
    }
    // The gap check runs over every frame type, `ping` included, because the
    // server numbers them all — restricting it to data frames would miss a
    // loss that happened to fall on a keepalive.
    if (this.lastSeq !== null && frame.seq !== this.lastSeq + 1) {
      this.resync();
      return;
    }
    this.lastSeq = frame.seq;

    switch (frame.type) {
      case "snapshot": {
        const data = asSnapshotData(frame.data);
        if (data) {
          this.everConnected = true;
          this.attempt = 0;
          this.emitStatus("live");
          this.handlers.onSnapshot(data);
        }
        return;
      }
      case "delta": {
        const data = asDeltaData(frame.data);
        if (data) {
          this.handlers.onDelta(data);
        }
        return;
      }
      case "ping": {
        this.socket?.send(PONG_MESSAGE);
        return;
      }
      default:
        // §6: unknown types (and `pong`, which this client never provokes)
        // are ignored, not errors. Slice 035's `activity` frame lands here
        // until the activity feed consumes it.
        return;
    }
  }

  /**
   * Drops the connection because the client's picture cannot be trusted.
   *
   * Used for a `seq` gap. Closing is the whole recovery: the close handler
   * schedules the reconnect and the new connection opens with a snapshot,
   * which §4.5 names as the only resync mechanism.
   */
  private resync(): void {
    // `detach` already closes the socket; the reconnect is then scheduled by
    // the same path a server-initiated close takes.
    this.detach();
    this.handleDisconnect();
  }

  private handleDisconnect(): void {
    this.detach();
    if (!this.started || this.retryTimer !== null) {
      return;
    }
    this.attempt += 1;
    this.emitStatus(this.everConnected ? "reconnecting" : "connecting");
    const delay = backoffDelayMs(this.attempt, this.backoff, this.random);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.started) {
        this.open();
      }
    }, delay);
  }

  /** Unhooks and closes the current socket without scheduling anything. */
  private detach(): void {
    const socket = this.socket;
    this.socket = null;
    if (!socket) {
      return;
    }
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    socket.close();
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private emitStatus(status: ConnectionStatus): void {
    if (this.status === status) {
      return;
    }
    this.status = status;
    this.handlers.onStatus(status);
  }
}
