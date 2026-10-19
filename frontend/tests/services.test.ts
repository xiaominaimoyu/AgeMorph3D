import assert from "node:assert/strict";
import { test, type TestContext } from "node:test";
import { CameraController, FrameStream, LocalApi, parseHealth } from "../src/services.ts";
import type { FaceState } from "../src/contracts.ts";

function replaceGlobal(t: TestContext, name: string, value: unknown): void {
  const previous = Object.getOwnPropertyDescriptor(globalThis, name);
  Object.defineProperty(globalThis, name, {
    configurable: true,
    writable: true,
    value,
  });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, name, previous);
    else Reflect.deleteProperty(globalThis, name);
  });
}

function photo(): Blob {
  return new Blob(["test image bytes"], { type: "image/jpeg" });
}

class VideoTrack extends EventTarget {
  readyState: MediaStreamTrackState = "live";
  stopped = false;
  stop(): void {
    this.stopped = true;
    this.readyState = "ended";
  }
  end(): void {
    this.readyState = "ended";
    this.dispatchEvent(new Event("ended"));
  }
}

class VideoStream {
  readonly track = new VideoTrack();
  get active(): boolean {
    return this.track.readyState === "live";
  }
  getTracks(): VideoTrack[] {
    return [this.track];
  }
  getVideoTracks(): VideoTrack[] {
    return [this.track];
  }
}

function reconstruction() {
  return {
    mesh_id: "face_001",
    topology_id: "test_topology",
    asset_mode: "age_morph",
    capabilities: { age_morph: true, age_texture: true },
    source_age: { value: 30, method: "user", calibration_id: null },
    shape: [0, 0.5],
    expr: [0],
    pose: { R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, 0] },
    texture_url: "/api/assets/face_001/texture.png",
  };
}

function serviceHealth() {
  return {
    api_version: "1.1",
    models: {
      detector: { state: "missing", backend: null, provider: null, detail: "Detector is not installed." },
      reconstructor: { state: "missing", backend: null, provider: null, detail: "Reconstructor is not installed." },
      age_shape: { state: "missing", backend: null, provider: null, detail: "Age model is not installed." },
      age_texture: { state: "missing", backend: null, provider: null, detail: "Texture model is not installed." },
    },
    capabilities: { reconstruction: false, age_morph: false, age_texture: false, realtime: false },
    device: "cpu",
    version: "0.1",
  };
}

test("health preserves missing and partial model states without deriving capabilities from model names", () => {
  const missing = serviceHealth();
  assert.deepEqual(parseHealth(missing), missing);
  const partial = serviceHealth();
  partial.models.detector = {
    state: "ready", backend: "detector-cpu", provider: "CPUExecutionProvider", detail: "Ready for local frames.",
  };
  partial.capabilities.realtime = true;
  assert.deepEqual(parseHealth(partial), partial);
  assert.equal(parseHealth(partial).capabilities?.reconstruction, false);
  assert.deepEqual(parseHealth({ ...partial, api_version: "1.2" }).capabilities, partial.capabilities);
});

test("legacy, missing, incomplete and non-boolean capability declarations never enable inference", () => {
  const good = serviceHealth();
  for (const payload of [
    { models: { detector: { loaded: true } }, device: "cpu", version: "legacy" },
    { ...good, capabilities: undefined },
    { ...good, api_version: undefined },
    { ...good, api_version: "1.0", capabilities: { ...good.capabilities, reconstruction: true } },
    { ...good, capabilities: { reconstruction: true } },
    { ...good, capabilities: { ...good.capabilities, reconstruction: "true" } },
    { ...good, capabilities: { ...good.capabilities, realtime: 1 } },
    { ...good, capabilities: [] },
    { ...good, capabilities: null },
  ]) assert.equal(parseHealth(payload).capabilities, null);
  const legacy = parseHealth({ models: { detector: "ready" }, device: "cpu", version: "legacy" });
  assert.equal(legacy.models.detector.state, "unknown");
  assert.match(legacy.models.detector.detail, /API 版本/);
});

class Clock {
  private id = 0;
  readonly timeouts = new Map<
    number,
    { callback: () => void; delay: number }
  >();
  readonly intervals = new Map<number, () => void>();
  setTimeout = (callback: () => void, delay: number): number => {
    const id = ++this.id;
    this.timeouts.set(id, { callback, delay });
    return id;
  };
  clearTimeout = (id: number): void => {
    this.timeouts.delete(id);
  };
  setInterval = (callback: () => void): number => {
    const id = ++this.id;
    this.intervals.set(id, callback);
    return id;
  };
  clearInterval = (id: number): void => {
    this.intervals.delete(id);
  };
  tick(): void {
    [...this.intervals.values()].forEach((callback) => callback());
  }
  expire(delay: number): void {
    const entry = [...this.timeouts].find(([, timer]) => timer.delay === delay);
    assert.ok(entry, `Expected an active ${delay} ms timeout`);
    this.timeouts.delete(entry[0]);
    entry[1].callback();
  }
}

test(
  "local service and assets cannot redirect photo traffic to other hosts",
  { concurrency: false },
  () => {
    for (const url of [
      "http://127.0.0.1:8000",
      "https://localhost:8000",
      "http://[::1]:8000",
    ]) {
      assert.ok(new LocalApi(url).baseUrl);
    }
    for (const url of [
      "http://example.com",
      "http://localhost@example.com",
      "http://user:pass@localhost",
      "http://localhost/api",
      "http://localhost?key=x",
      "http://localhost#x",
      "file:///localhost",
    ])
      assert.throws(() => new LocalApi(url));

    const api = new LocalApi();
    assert.equal(
      api.assetUrl("face_001"),
      "http://127.0.0.1:8000/api/assets/face_001/mesh.glb",
    );
    assert.equal(
      api.safeAssetUrl("/api/assets/face_001/t.png"),
      "http://127.0.0.1:8000/api/assets/face_001/t.png",
    );
    for (const id of ["../mesh", "a/b", "x?y"])
      assert.throws(() => api.assetUrl(id));
    for (const url of [
      "https://other.test/api/assets/t.png",
      "http://localhost:8000/api/assets/t.png",
      "/api/assets/../private",
      "http://user@127.0.0.1:8000/api/assets/x",
    ])
      assert.throws(() => api.safeAssetUrl(url));
  },
);

test(
  "reconstruction sends multipart image without cookies and validates returned assets",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", globalThis);
    replaceGlobal(t, "fetch", async (url: string, init: RequestInit) => {
      assert.equal(url, "http://127.0.0.1:8000/api/reconstruct");
      assert.equal(init.method, "POST");
      assert.equal(init.redirect, "error");
      assert.equal(init.credentials, "omit");
      assert.equal(init.cache, "no-store");
      assert.ok(init.body instanceof FormData);
      const file = init.body.get("image");
      assert.ok(file instanceof Blob);
      assert.equal(file.type, "image/jpeg");
      assert.equal(init.body.has("source_age"), false);
      return Response.json(reconstruction());
    });
    const result = await new LocalApi().reconstruct(photo());
    assert.equal(result.mesh_id, "face_001");
    assert.deepEqual(result.shape, [0, 0.5]);
    assert.equal(
      result.texture_url,
      "http://127.0.0.1:8000/api/assets/face_001/texture.png",
    );
  },
);

test(
  "optional user source age is sent explicitly and never taken from a demo age",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", globalThis);
    let requests = 0;
    replaceGlobal(t, "fetch", async (_url: string, init: RequestInit) => {
      requests++;
      assert.ok(init.body instanceof FormData);
      assert.equal(init.body.get("source_age"), "42.5");
      return Response.json(reconstruction());
    });
    const api = new LocalApi();
    await api.reconstruct(photo(), undefined, 42.5);
    for (const invalid of [19, 71, NaN, Infinity, true])
      await assert.rejects(api.reconstruct(photo(), undefined, invalid as number), /源年龄/);
    assert.equal(requests, 1);
  },
);

test(
  "static results preserve unknown source age and independently declare texture ability",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", globalThis);
    let payload: unknown = {
      ...reconstruction(), asset_mode: "static", capabilities: { age_morph: false, age_texture: false },
      source_age: { value: null, method: "unknown", calibration_id: null }, texture_url: undefined,
    };
    replaceGlobal(t, "fetch", async () => Response.json(payload));
    const result = await new LocalApi().reconstruct(photo());
    assert.equal(result.asset_mode, "static");
    assert.deepEqual(result.source_age, { value: null, method: "unknown", calibration_id: null });
    assert.equal(result.texture_url, undefined);
    payload = {
      ...reconstruction(), asset_mode: "static", capabilities: { age_morph: false, age_texture: true },
      source_age: { value: 42.5, method: "estimated", calibration_id: "calibration_v1" },
    };
    assert.equal((await new LocalApi().reconstruct(photo())).capabilities.age_texture, true);
  },
);

test(
  "reconstruction rejects legacy successes, contradictory modes and uncalibrated age capabilities",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", globalThis);
    let payload: unknown;
    replaceGlobal(t, "fetch", async () => Response.json(payload));
    const unknownAge = { value: null, method: "unknown", calibration_id: null };
    const invalid: unknown[] = [
      { mesh_id: "legacy", shape: [0], expr: [0], pose: reconstruction().pose },
      { ...reconstruction(), asset_mode: "static" },
      { ...reconstruction(), asset_mode: "other" },
      { ...reconstruction(), capabilities: { age_morph: false, age_texture: true } },
      { ...reconstruction(), capabilities: { age_morph: true } },
      { ...reconstruction(), capabilities: { age_morph: true, age_texture: "true" } },
      { ...reconstruction(), topology_id: "../mesh" },
      { ...reconstruction(), topology_id: "a".repeat(101) },
      { ...reconstruction(), source_age: unknownAge },
      { ...reconstruction(), source_age: { value: 30, method: "unknown", calibration_id: null } },
      { ...reconstruction(), source_age: { value: 19, method: "user", calibration_id: null } },
      { ...reconstruction(), source_age: { value: 71, method: "user", calibration_id: null } },
      { ...reconstruction(), source_age: { value: 30, method: "user", calibration_id: "not_null" } },
      { ...reconstruction(), source_age: { value: 30, method: "estimated", calibration_id: null } },
      { ...reconstruction(), source_age: { value: 30, method: "estimated", calibration_id: "../id" } },
      { ...reconstruction(), source_age: { value: 30, method: "other", calibration_id: null } },
      { ...reconstruction(), texture_url: undefined },
      { ...reconstruction(), asset_mode: "static", capabilities: { age_morph: false, age_texture: true }, source_age: unknownAge },
    ];
    for (const field of ["topology_id", "asset_mode", "capabilities", "source_age"]) {
      const missing = { ...reconstruction() } as Record<string, unknown>;
      delete missing[field];
      invalid.push(missing);
    }
    for (payload of invalid) await assert.rejects(new LocalApi().reconstruct(photo()));
  },
);

test(
  "health and aging use the documented fields without inventing model readiness",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", globalThis);
    replaceGlobal(t, "fetch", async (url: string, init: RequestInit) => {
      if (url.endsWith("/api/health")) {
        return Response.json(serviceHealth());
      }
      assert.equal(url, "http://127.0.0.1:8000/api/aging");
      assert.equal(init.method, "POST");
      assert.deepEqual(JSON.parse(String(init.body)), {
        mesh_id: "face_001",
        age: 45,
      });
      return Response.json({ shape_aged: [1, 2] });
    });
    const api = new LocalApi();
    assert.deepEqual(await api.health(), serviceHealth());
    assert.deepEqual(await api.aging("face_001", 45), { shape_aged: [1, 2] });
    await assert.rejects(api.aging("face_001", 71), /年龄/);
  },
);

test(
  "invalid files are rejected before any network request",
  { concurrency: false },
  async (t) => {
    let requests = 0;
    replaceGlobal(t, "fetch", async () => {
      requests++;
      throw new Error("Network must not be reached");
    });
    const api = new LocalApi();
    for (const image of [
      new Blob([], { type: "image/jpeg" }),
      new Blob(["svg"], { type: "image/svg+xml" }),
      new Blob([new Uint8Array(10 * 1024 * 1024 + 1)], { type: "image/png" }),
    ])
      await assert.rejects(api.reconstruct(image), /10 MB/);
    assert.equal(requests, 0);
  },
);

test(
  "malformed parameters and external texture URLs never reach the renderer",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", globalThis);
    let payload: unknown;
    replaceGlobal(t, "fetch", async () => Response.json(payload));
    for (const invalid of [
      { ...reconstruction(), shape: [null] },
      { ...reconstruction(), expr: [] },
      { ...reconstruction(), pose: { R: [1, 2], t: [0, 0, 0] } },
      { ...reconstruction(), shape: Array(301).fill(0) },
      { ...reconstruction(), mesh_id: "../private" },
      { ...reconstruction(), texture_url: "https://example.com/t.png" },
    ]) {
      payload = invalid;
      await assert.rejects(new LocalApi().reconstruct(photo()));
    }
  },
);

test(
  "HTTP, non-JSON and oversized responses produce actionable errors",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", globalThis);
    let response: Response;
    replaceGlobal(t, "fetch", async () => response);
    response = new Response("server error", { status: 503 });
    await assert.rejects(new LocalApi().health(), /HTTP 503/);
    response = Response.json({ detail: "模型尚未加载" }, { status: 409 });
    await assert.rejects(new LocalApi().health(), /模型尚未加载/);
    response = new Response("<html>not the API</html>");
    await assert.rejects(new LocalApi().health(), /有效 JSON/);
    response = new Response(`{"a":"${"x".repeat(140 * 1024)}"}`);
    await assert.rejects(new LocalApi().health(), /响应过大/);
  },
);

test(
  "request cancellation stays distinguishable from a 30-second timeout and clears timers",
  { concurrency: false },
  async (t) => {
    const clock = new Clock();
    replaceGlobal(t, "window", clock);
    replaceGlobal(
      t,
      "fetch",
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const api = new LocalApi();
    const controller = new AbortController();
    const pending = api.reconstruct(photo(), controller.signal);
    controller.abort();
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(clock.timeouts.size, 0);
    await assert.rejects(api.reconstruct(photo(), controller.signal), {
      name: "AbortError",
    });
    assert.equal(clock.timeouts.size, 0);

    const timeout = api.health();
    clock.expire(30_000);
    await assert.rejects(timeout, /30 秒/);
    assert.equal(clock.timeouts.size, 0);
  },
);

test(
  "stopping while camera permission is pending closes late streams",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", { isSecureContext: true });
    let grant!: (stream: unknown) => void;
    let permissions = 0;
    replaceGlobal(t, "navigator", {
      mediaDevices: {
        getUserMedia: (constraints: MediaStreamConstraints) => {
          assert.equal(constraints.audio, false);
          permissions++;
          return new Promise((resolve) => {
            grant = resolve;
          });
        },
      },
    });
    const video = { srcObject: null, pause() {}, async play() {} };
    const camera = new CameraController(video as unknown as HTMLVideoElement);
    const first = camera.start();
    assert.equal(camera.start(), first);
    camera.stop();
    const acquired = new VideoStream();
    grant(acquired);
    await assert.rejects(first, { name: "AbortError" });
    assert.equal(permissions, 1);
    assert.equal(acquired.track.stopped, true);
    assert.equal(camera.active, false);
    assert.equal(video.srcObject, null);
  },
);

test(
  "denied camera permission explains how to recover without leaving a source attached",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", { isSecureContext: true });
    replaceGlobal(t, "navigator", {
      mediaDevices: {
        getUserMedia: async () => {
          throw new DOMException("Permission denied", "NotAllowedError");
        },
      },
    });
    const video = { srcObject: null, pause() {}, async play() {} };
    const camera = new CameraController(video as unknown as HTMLVideoElement);
    await assert.rejects(camera.start(), /摄像头权限/);
    assert.equal(video.srcObject, null);
    assert.equal(camera.active, false);
  },
);

test(
  "unexpected camera track end notifies once and manual stops detach old track listeners",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", { isSecureContext: true });
    const acquired: VideoStream[] = [];
    replaceGlobal(t, "navigator", {
      mediaDevices: {
        getUserMedia: async () => {
          const stream = new VideoStream();
          acquired.push(stream);
          return stream;
        },
      },
    });
    const video = { srcObject: null, pause() {}, async play() {} };
    let ended = 0;
    const camera = new CameraController(
      video as unknown as HTMLVideoElement,
      () => {
        ended++;
      },
    );
    await camera.start();
    assert.equal(camera.active, true);
    acquired[0]!.track.end();
    acquired[0]!.track.end();
    assert.equal(ended, 1);
    assert.equal(camera.active, false);
    assert.equal(video.srcObject, null);

    await camera.start();
    camera.stop();
    acquired[1]!.track.end();
    assert.equal(
      ended,
      1,
      "manual stop must not report an unexpected disconnect",
    );
    await camera.start();
    acquired[1]!.track.end();
    assert.equal(
      camera.active,
      true,
      "old track events cannot stop a new camera session",
    );
    acquired[2]!.track.end();
    assert.equal(ended, 2);
    assert.equal(video.srcObject, null);
  },
);

test(
  "camera track ending while playback starts cancels the pending startup",
  { concurrency: false },
  async (t) => {
    replaceGlobal(t, "window", { isSecureContext: true });
    const acquired = new VideoStream();
    replaceGlobal(t, "navigator", {
      mediaDevices: { getUserMedia: async () => acquired },
    });
    let finishPlayback!: () => void;
    const video = {
      srcObject: null,
      pause() {},
      play: () =>
        new Promise<void>((resolve) => {
          finishPlayback = resolve;
        }),
    };
    let ended = 0;
    const camera = new CameraController(
      video as unknown as HTMLVideoElement,
      () => {
        ended++;
      },
    );
    const startup = camera.start();
    await Promise.resolve();
    acquired.track.end();
    finishPlayback();
    await assert.rejects(startup, { name: "AbortError" });
    assert.equal(ended, 1);
    assert.equal(camera.active, false);
    assert.equal(video.srcObject, null);
  },
);

function streamingEnvironment(t: TestContext) {
  let stream: FrameStream | undefined;
  // Stop while the browser globals are still installed; Node runs after hooks in registration order.
  t.after(() => stream?.stop());
  const clock = new Clock();
  replaceGlobal(t, "window", clock);
  replaceGlobal(t, "MediaStream", VideoStream);
  replaceGlobal(t, "HTMLMediaElement", { HAVE_CURRENT_DATA: 2 });
  const encodes: {
    resolve: (blob: Blob) => void;
    width: number;
    height: number;
    quality: number;
  }[] = [];
  replaceGlobal(t, "document", {
    createElement: () => ({
      width: 0,
      height: 0,
      getContext() {
        return { drawImage() {} };
      },
      toBlob(resolve: (blob: Blob) => void, type: string, quality: number) {
        assert.equal(type, "image/jpeg");
        encodes.push({
          resolve,
          width: this.width,
          height: this.height,
          quality,
        });
      },
    }),
  });
  const sockets: Socket[] = [];
  class Socket {
    static OPEN = 1;
    static CONNECTING = 0;
    readyState = 0;
    bufferedAmount = 0;
    sent: Blob[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: unknown }) => void) | null = null;
    onerror: (() => void) | null = null;
    onclose: (() => void) | null = null;
    constructor(readonly url: string) {
      sockets.push(this);
    }
    send(blob: Blob): void {
      this.sent.push(blob);
    }
    close(): void {
      this.readyState = 3;
    }
    open(): void {
      this.readyState = 1;
      this.onopen?.();
    }
    receive(data: unknown): void {
      this.onmessage?.({
        data: typeof data === "string" ? data : JSON.stringify(data),
      });
    }
  }
  replaceGlobal(t, "WebSocket", Socket);
  const video = {
    srcObject: new VideoStream(),
    readyState: 2,
    videoWidth: 1920,
    videoHeight: 1080,
  };
  const states: FaceState[] = [];
  const errors: string[] = [];
  stream = new FrameStream(
    new LocalApi(),
    video as unknown as HTMLVideoElement,
    {
      onState: (state) => states.push(state),
      onError: (message) => errors.push(message),
    },
  );
  return { clock, encodes, sockets, states, errors, stream, video };
}

function frame(seq = 1) {
  return {
    type: "face_state",
    seq,
    ts: 123,
    bbox: [10, 10, 100, 100],
    landmarks: [
      [20, 20],
      [30, 20],
      [25, 30],
      [20, 40],
      [30, 40],
    ],
    pose: reconstruction().pose,
    conf: 0.9,
  };
}

test(
  "realtime frames apply backpressure and ignore stale sequence numbers",
  { concurrency: false },
  async (t) => {
    const env = streamingEnvironment(t);
    env.stream.start();
    const socket = env.sockets[0]!;
    assert.equal(socket.url, "ws://127.0.0.1:8000/ws/frame");
    socket.open();
    assert.equal(env.encodes.length, 1);
    assert.deepEqual(
      [env.encodes[0]!.width, env.encodes[0]!.height, env.encodes[0]!.quality],
      [640, 360, 0.7],
    );
    env.encodes[0]!.resolve(photo());
    await Promise.resolve();
    env.clock.tick();
    env.clock.tick();
    assert.equal(env.encodes.length, 1);
    assert.equal(socket.sent.length, 1);
    socket.receive({ type: "status", device: "cpu", fps: 9 });
    env.clock.tick();
    assert.equal(env.encodes.length, 1, "status must not acknowledge a frame");

    socket.receive(frame());
    assert.equal(env.states.length, 1);
    assert.equal(env.states[0]!.shape, undefined);
    env.clock.tick();
    assert.equal(env.encodes.length, 2);
    env.encodes[1]!.resolve(photo());
    await Promise.resolve();
    socket.receive(frame());
    env.clock.tick();
    assert.equal(
      env.encodes.length,
      2,
      "an old sequence must not release backpressure",
    );
    assert.equal(env.states.length, 1);
    socket.receive(frame(2));
    assert.equal(env.states.length, 2);
  },
);

test(
  "invalid realtime messages close the connection and release all timers",
  { concurrency: false },
  async (t) => {
    for (const data of [
      "x".repeat(1025),
      { ...frame(), landmarks: [[1, 2]] },
      { ...frame(), seq: 1.5 },
    ]) {
      await t.test(
        typeof data === "string" ? "oversized" : JSON.stringify(data),
        { concurrency: false },
        (nested) => {
          const env = streamingEnvironment(nested);
          env.stream.start();
          const socket = env.sockets[0]!;
          socket.open();
          socket.receive(data);
          assert.equal(env.errors.length, 1);
          assert.equal(socket.readyState, 3);
          assert.equal(env.clock.timeouts.size, 0);
          assert.equal(env.clock.intervals.size, 0);
        },
      );
    }
  },
);

test(
  "stopping during frame encoding cannot send a late frame",
  { concurrency: false },
  async (t) => {
    const env = streamingEnvironment(t);
    env.stream.start();
    const socket = env.sockets[0]!;
    socket.open();
    env.stream.stop();
    env.encodes[0]!.resolve(photo());
    await Promise.resolve();
    assert.equal(socket.sent.length, 0);
    assert.equal(env.clock.timeouts.size, 0);
    assert.equal(env.clock.intervals.size, 0);
  },
);

test(
  "realtime connection requires a live video track rather than a retained video frame",
  { concurrency: false },
  (t) => {
    const env = streamingEnvironment(t);
    env.video.srcObject.track.end();
    env.stream.start();
    assert.equal(env.sockets.length, 0);
    assert.match(env.errors[0]!, /摄像头/);
  },
);

test(
  "camera loss while encoding or awaiting detection stops without sending retained frames",
  { concurrency: false },
  async (t) => {
    for (const phase of ["encoding", "awaiting-result"]) {
      await t.test(phase, { concurrency: false }, async (nested) => {
        const env = streamingEnvironment(nested);
        env.stream.start();
        const socket = env.sockets[0]!;
        socket.open();
        if (phase === "awaiting-result") {
          env.encodes[0]!.resolve(photo());
          await Promise.resolve();
        }
        env.video.srcObject.track.end();
        if (phase === "encoding") {
          env.encodes[0]!.resolve(photo());
          await Promise.resolve();
        } else env.clock.tick();
        assert.equal(socket.sent.length, phase === "encoding" ? 0 : 1);
        assert.equal(socket.readyState, 3);
        assert.match(env.errors[0]!, /摄像头已断开/);
        assert.equal(env.clock.timeouts.size, 0);
        assert.equal(env.clock.intervals.size, 0);
      });
    }
  },
);

test(
  "unresponsive realtime service stops after its deadline and does not reconnect",
  { concurrency: false },
  async (t) => {
    const env = streamingEnvironment(t);
    env.stream.start();
    const socket = env.sockets[0]!;
    socket.open();
    env.encodes[0]!.resolve(photo());
    await Promise.resolve();
    env.clock.expire(8_000);
    assert.equal(socket.readyState, 3);
    assert.equal(env.sockets.length, 1);
    assert.match(env.errors[0]!, /8 秒/);
    assert.equal(env.clock.timeouts.size, 0);
    assert.equal(env.clock.intervals.size, 0);
  },
);
