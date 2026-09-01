import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ActivityEvent } from "@/lib/api/activity";
import { DEFAULT_BACKOFF } from "@/lib/ws/backoff";
import type { ConnectionStatus, LiveSocketLike } from "@/lib/ws/liveSocket";
import { LiveSocket, liveSocketUrl } from "@/lib/ws/liveSocket";
import type { DeltaData, SnapshotData } from "@/lib/ws/protocol";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import {
  FakeWebSocket,
  getLastWebSocket,
  resetWebSocketMock,
} from "@/test/webSocketMock";

interface Harness {
  socket: LiveSocket;
  snapshots: SnapshotData[];
  deltas: DeltaData[];
  statuses: ConnectionStatus[];
}

function harness(): Harness {
  const snapshots: SnapshotData[] = [];
  const deltas: DeltaData[] = [];
  const statuses: ConnectionStatus[] = [];
  const socket = new LiveSocket({
    url: "ws://test/api/v1/ws/live",
    socketFactory: (url) => new FakeWebSocket(url) as unknown as LiveSocketLike,
    // No jitter: the tests assert on exact retry delays, and the jitter's own
    // distribution is `backoff.test.ts`'s subject.
    random: () => 0,
    onSnapshot: (data) => snapshots.push(data),
    onDelta: (data) => deltas.push(data),
    onStatus: (status) => statuses.push(status),
  });
  return { socket, snapshots, deltas, statuses };
}

function snapshotFrame(seq: number) {
  return {
    type: "snapshot",
    seq,
    data: { aircraft: [makeAircraft()], receiver: { timezone: "UTC" } },
  };
}

beforeEach(() => {
  resetWebSocketMock();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("liveSocketUrl", () => {
  it("derives ws:// from a plain-http origin", () => {
    expect(liveSocketUrl({ protocol: "http:", host: "pi.local:5173" })).toBe(
      "ws://pi.local:5173/api/v1/ws/live",
    );
  });

  it("upgrades to wss:// on an https origin", () => {
    // Mixed content: a ws:// socket from an https page is blocked outright.
    expect(liveSocketUrl({ protocol: "https:", host: "flightsite" })).toBe(
      "wss://flightsite/api/v1/ws/live",
    );
  });
});

describe("LiveSocket", () => {
  it("reports connecting, then live once the snapshot lands", () => {
    const { socket, snapshots, statuses } = harness();
    socket.start();
    expect(statuses).toEqual(["connecting"]);

    getLastWebSocket().emitFrame(snapshotFrame(1));

    expect(statuses).toEqual(["connecting", "live"]);
    expect(socket.connectionStatus).toBe("live");
    expect(snapshots).toHaveLength(1);
    expect(snapshots[0]?.aircraft).toHaveLength(1);
    socket.stop();
  });

  it("hands snapshot and delta frames on in arrival order", () => {
    const { socket, snapshots, deltas } = harness();
    socket.start();
    const ws = getLastWebSocket();

    ws.emitFrame(snapshotFrame(1));
    ws.emitFrame({
      type: "delta",
      seq: 2,
      data: {
        updated: [makeAircraft({ icao: "a9c2f0" })],
        stale: [],
        removed: [],
      },
    });
    ws.emitFrame({
      type: "delta",
      seq: 3,
      data: { updated: [], stale: ["ae1463"], removed: ["a9c2f0"] },
    });

    expect(snapshots).toHaveLength(1);
    expect(deltas.map((delta) => delta.removed)).toEqual([[], ["a9c2f0"]]);
    expect(deltas[1]?.stale).toEqual(["ae1463"]);
    socket.stop();
  });

  it("answers an application-level ping with a pong", () => {
    // §4.5: the server drops a client that has sent nothing across two pings.
    const { socket } = harness();
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    ws.emitFrame({ type: "ping", seq: 2 });

    expect(ws.sent).toEqual([JSON.stringify({ type: "pong" })]);
    socket.stop();
  });

  it("ignores unknown frame types without dropping the connection", () => {
    const { socket, deltas } = harness();
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    ws.emitFrame({ type: "maintenance_issue", seq: 2, data: { kind: "disk" } });
    ws.emitFrame({
      type: "delta",
      seq: 3,
      data: { updated: [], stale: [], removed: [] },
    });

    expect(ws.closed).toBe(false);
    expect(deltas).toHaveLength(1);
    socket.stop();
  });

  it("ignores an activity frame when the consumer does not handle them", () => {
    // Slice 035 added `activity` to this socket, and `onActivity` is optional
    // precisely so a consumer that predates it — or simply does not want the
    // feed — keeps the slice-010 behaviour: the frame falls through to §6's
    // ignore path, the sequence still advances, and nothing resyncs.
    const { socket, deltas } = harness();
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    ws.emitFrame({
      type: "activity",
      seq: 2,
      data: { id: 4021, type: "milestone" },
    });
    ws.emitFrame({
      type: "delta",
      seq: 3,
      data: { updated: [], stale: [], removed: [] },
    });

    expect(ws.closed).toBe(false);
    expect(deltas).toHaveLength(1);
    socket.stop();
  });

  it("hands an activity frame to a consumer that does handle them", () => {
    const events: ActivityEvent[] = [];
    const socket = new LiveSocket({
      url: "ws://test/api/v1/ws/live",
      socketFactory: (url) =>
        new FakeWebSocket(url) as unknown as LiveSocketLike,
      random: () => 0,
      onActivity: (event) => events.push(event),
    });
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    ws.emitFrame({
      type: "activity",
      seq: 2,
      data: {
        id: 4021,
        type: "range_record",
        severity: "interesting",
        at: "2026-08-31T14:03:22.418Z",
        icao: "ae1463",
        sighting_id: 88213,
        payload: { range_nm: 412.75 },
      },
    });

    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(4021);
    expect(events[0]?.type).toBe("range_record");
    expect(events[0]?.payload).toEqual({ range_nm: 412.75 });
    expect(ws.closed).toBe(false);
    socket.stop();
  });

  it("drops an unreadable activity frame without breaking the stream", () => {
    const events: ActivityEvent[] = [];
    const deltas: DeltaData[] = [];
    const socket = new LiveSocket({
      url: "ws://test/api/v1/ws/live",
      socketFactory: (url) =>
        new FakeWebSocket(url) as unknown as LiveSocketLike,
      random: () => 0,
      onActivity: (event) => events.push(event),
      onDelta: (data) => deltas.push(data),
    });
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    // No `id`: nothing the feed could dedupe on or render. The frame is
    // dropped, but its `seq` was still consumed, so the next delta applies.
    ws.emitFrame({ type: "activity", seq: 2, data: { type: "milestone" } });
    ws.emitFrame({
      type: "delta",
      seq: 3,
      data: { updated: [], stale: [], removed: [] },
    });

    expect(events).toEqual([]);
    expect(deltas).toHaveLength(1);
    expect(ws.closed).toBe(false);
    socket.stop();
  });

  it("ignores unparseable frames without advancing the sequence", () => {
    const { socket, deltas } = harness();
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    ws.emitRaw("not json at all");
    ws.emitFrame({
      type: "delta",
      seq: 2,
      data: { updated: [], stale: [], removed: [] },
    });

    expect(ws.closed).toBe(false);
    expect(deltas).toHaveLength(1);
    socket.stop();
  });

  it("reconnects with backoff after a close and takes a fresh snapshot", () => {
    const { socket, snapshots, statuses } = harness();
    socket.start();
    getLastWebSocket().emitFrame(snapshotFrame(1));
    const first = getLastWebSocket();

    // 1013 is the server's slow-consumer drop; every close code takes the
    // same path, because reconnect-and-resync is the only recovery there is.
    first.emitClose(1013);
    expect(statuses).toEqual(["connecting", "live", "reconnecting"]);
    expect(FakeWebSocket.instances).toHaveLength(1);

    vi.advanceTimersByTime(DEFAULT_BACKOFF.baseDelayMs / 2);
    expect(FakeWebSocket.instances).toHaveLength(2);

    getLastWebSocket().emitFrame(snapshotFrame(1));
    expect(snapshots).toHaveLength(2);
    expect(socket.connectionStatus).toBe("live");
    socket.stop();
  });

  it("lengthens the delay while reconnection keeps failing", () => {
    const { socket } = harness();
    socket.start();
    getLastWebSocket().emitFrame(snapshotFrame(1));

    getLastWebSocket().emitClose();
    vi.advanceTimersByTime(250);
    expect(FakeWebSocket.instances).toHaveLength(2);

    getLastWebSocket().emitClose();
    // Second attempt waits 500 ms (1000 / 2), not 250.
    vi.advanceTimersByTime(250);
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(250);
    expect(FakeWebSocket.instances).toHaveLength(3);
    socket.stop();
  });

  it("stays in connecting while a first connection has never succeeded", () => {
    const { socket, statuses } = harness();
    socket.start();
    getLastWebSocket().emitClose();
    vi.advanceTimersByTime(250);
    getLastWebSocket().emitClose();

    // "Reconnecting" would claim there was something to reconnect to.
    expect(statuses).toEqual(["connecting"]);
    socket.stop();
  });

  it("treats a socket error like a close", () => {
    const { socket } = harness();
    socket.start();
    getLastWebSocket().emitError();
    vi.advanceTimersByTime(250);
    expect(FakeWebSocket.instances).toHaveLength(2);
    socket.stop();
  });

  it("forces a reconnect when the sequence gaps", () => {
    // The server never leaves a gap — it disconnects a client it cannot
    // deliver to in order — so a gap means frames were lost in transit and
    // the whole client picture is suspect.
    const { socket, snapshots, deltas } = harness();
    socket.start();
    const first = getLastWebSocket();
    first.emitFrame(snapshotFrame(1));
    first.emitFrame({
      type: "delta",
      seq: 5,
      data: { updated: [makeAircraft()], stale: [], removed: [] },
    });

    expect(deltas).toHaveLength(0);
    expect(first.closed).toBe(true);

    vi.advanceTimersByTime(250);
    expect(FakeWebSocket.instances).toHaveLength(2);
    getLastWebSocket().emitFrame(snapshotFrame(1));
    expect(snapshots).toHaveLength(2);
    socket.stop();
  });

  it("counts a keepalive frame in the sequence check", () => {
    const { socket, deltas } = harness();
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    ws.emitFrame({ type: "ping", seq: 2 });
    ws.emitFrame({
      type: "delta",
      seq: 3,
      data: { updated: [], stale: [], removed: [] },
    });

    expect(ws.closed).toBe(false);
    expect(deltas).toHaveLength(1);
    socket.stop();
  });

  it("accepts a mid-stream resync snapshot without a gap", () => {
    // The broadcaster resyncs by sending a snapshot on the same connection,
    // continuing the sequence.
    const { socket, snapshots } = harness();
    socket.start();
    const ws = getLastWebSocket();
    ws.emitFrame(snapshotFrame(1));
    ws.emitFrame({
      type: "delta",
      seq: 2,
      data: { updated: [], stale: [], removed: [] },
    });
    ws.emitFrame(snapshotFrame(3));

    expect(ws.closed).toBe(false);
    expect(snapshots).toHaveLength(2);
    socket.stop();
  });

  it("stops reconnecting once stopped", () => {
    const { socket } = harness();
    socket.start();
    getLastWebSocket().emitFrame(snapshotFrame(1));
    socket.stop();
    expect(getLastWebSocket().closed).toBe(true);

    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("ignores a repeated start", () => {
    const { socket, statuses } = harness();
    socket.start();
    socket.start();
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(statuses).toEqual(["connecting"]);
    socket.stop();
  });

  it("ignores frames from a socket it has already discarded", () => {
    const { socket, deltas } = harness();
    socket.start();
    const first = getLastWebSocket();
    first.emitFrame(snapshotFrame(1));
    socket.stop();
    first.emitFrame({
      type: "delta",
      seq: 2,
      data: { updated: [makeAircraft()], stale: [], removed: [] },
    });
    expect(deltas).toHaveLength(0);
  });
});
