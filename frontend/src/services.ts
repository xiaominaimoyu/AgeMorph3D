import type {
  AgingResult,
  Capabilities,
  FaceState,
  FrameCallbacks,
  Health,
  ModelStatus,
  Pose,
  Reconstruction,
  SourceAge,
} from "./contracts";
import { assertRotation, type FrameSize } from "./realtime.ts";

const REQUEST_TIMEOUT = 30_000;
const MAX_JSON_BYTES = 128 * 1024;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_FRAME_MESSAGE_BYTES = 1024;
const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}格式不正确。`);
  }
  return value as Record<string, unknown>;
}

function boundedString(value: unknown, label: string, limit = 200): string {
  if (typeof value !== "string" || !value.trim() || value.length > limit) {
    throw new Error(`${label}缺失或长度不正确。`);
  }
  return value;
}

function finite(value: unknown, label: string, min = -1e6, max = 1e6): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < min ||
    value > max
  ) {
    throw new Error(`${label}包含无效数值。`);
  }
  return value;
}

function vector(
  value: unknown,
  label: string,
  length?: number,
  maxLength = 300,
): number[] {
  if (
    !Array.isArray(value) ||
    value.length === 0 ||
    value.length > maxLength ||
    (length !== undefined && value.length !== length)
  ) {
    throw new Error(`${label}维度不正确。`);
  }
  return value.map((item) => finite(item, label));
}

function pose(value: unknown): Pose {
  const data = record(value, "姿态");
  const R = vector(data.R, "旋转矩阵", 9);
  R.forEach((item) => finite(item, "旋转矩阵", -1.001, 1.001));
  assertRotation(R);
  return { R, t: vector(data.t, "平移向量", 3) };
}

function meshId(value: unknown): string {
  const id = boundedString(value, "模型标识", 100);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(id))
    throw new Error("模型标识只能包含字母、数字、下划线和短横线。");
  return id;
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function cancelled(): DOMException {
  return new DOMException("操作已取消。", "AbortError");
}

/** Legacy health can be displayed; inference needs all four v1.1/1.2 booleans. */
export function parseHealth(value: unknown): Health {
  const data = record(value, "服务状态");
  const validText = (item: unknown): item is string | null =>
    item === null || (typeof item === "string" && item.length <= 200);
  const models = Object.fromEntries(
    Object.entries(record(data.models, "模型状态")).map(([name, value]): [string, ModelStatus] => {
      const status = value !== null && typeof value === "object" && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
      if (
        typeof status.state === "string" &&
        ["missing", "loading", "ready", "error"].includes(status.state) &&
        validText(status.backend) &&
        validText(status.provider) &&
        typeof status.detail === "string" &&
        status.detail.length <= 2000
      ) {
        return [name, {
          state: status.state as ModelStatus["state"],
          backend: status.backend,
          provider: status.provider,
          detail: status.detail,
        }];
      }
      return [name, {
        state: "unknown",
        backend: null,
        provider: null,
        detail: "模型状态格式未知，请检查 API 版本。",
      }];
    }),
  );
  const apiVersion =
    typeof data.api_version === "string" && data.api_version.length <= 80
      ? data.api_version
      : null;
  let capabilities: Capabilities | null = null;
  const flags = data.capabilities;
  if (
    (apiVersion === "1.1" || apiVersion === "1.2") &&
    flags !== null &&
    typeof flags === "object" &&
    !Array.isArray(flags)
  ) {
    const values = flags as Record<string, unknown>;
    if (
      ["reconstruction", "age_morph", "age_texture", "realtime"].every(
        (key) => typeof values[key] === "boolean",
      )
    ) {
      capabilities = {
        reconstruction: values.reconstruction as boolean,
        age_morph: values.age_morph as boolean,
        age_texture: values.age_texture as boolean,
        realtime: values.realtime as boolean,
      };
    }
  }
  return {
    models,
    device: boundedString(data.device, "推理设备", 80),
    version: boundedString(data.version, "服务版本", 80),
    api_version: apiVersion,
    capabilities,
  };
}

function sourceAge(value: unknown): SourceAge {
  const data = record(value, "源年龄");
  if (data.method === "unknown") {
    if (data.value !== null || data.calibration_id !== null)
      throw new Error("未知源年龄必须使用空年龄和空校准标识。");
    return { value: null, method: "unknown", calibration_id: null };
  }
  if (data.method !== "user" && data.method !== "estimated")
    throw new Error("源年龄方法必须为 unknown、user 或 estimated。");
  const age = finite(data.value, "源年龄", 20, 70);
  if (data.method === "user") {
    if (data.calibration_id !== null)
      throw new Error("用户提供的源年龄不能带模型校准标识。");
    return { value: age, method: "user", calibration_id: null };
  }
  return { value: age, method: "estimated", calibration_id: meshId(data.calibration_id) };
}

/** All photo traffic stays on an explicitly selected loopback origin. */
export class LocalApi {
  readonly baseUrl: string;

  constructor(baseUrl = "http://127.0.0.1:8000") {
    let url: URL;
    try {
      url = new URL(baseUrl);
    } catch {
      throw new Error("请输入完整的本地服务地址，例如 http://127.0.0.1:8000。");
    }
    if (
      !["http:", "https:"].includes(url.protocol) ||
      !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    ) {
      throw new Error(
        "服务地址仅允许本机 localhost、127.0.0.1 或 [::1]，不能包含账号、路径或查询参数。",
      );
    }
    this.baseUrl = url.origin;
  }

  websocketUrl(): string {
    const url = new URL("/ws/frame", this.baseUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.href;
  }

  safeAssetUrl(path: string): string {
    let url: URL;
    try {
      url = new URL(boundedString(path, "资产地址", 2048), `${this.baseUrl}/`);
    } catch {
      throw new Error("资产地址格式不正确。");
    }
    if (
      url.origin !== this.baseUrl ||
      url.username ||
      url.password ||
      !url.pathname.startsWith("/api/assets/") ||
      url.hash
    ) {
      throw new Error("资产必须来自当前本地服务的 /api/assets/ 目录。");
    }
    return url.href;
  }

  assetUrl(id: string): string {
    return `${this.baseUrl}/api/assets/${encodeURIComponent(meshId(id))}/mesh.glb`;
  }

  async health(signal?: AbortSignal): Promise<Health> {
    return parseHealth(await this.request("/api/health", {}, signal));
  }

  async reconstruct(file: Blob, signal?: AbortSignal, sourceAgeValue?: number): Promise<Reconstruction> {
    if (
      !IMAGE_TYPES.has(file.type) ||
      file.size === 0 ||
      file.size > MAX_IMAGE_BYTES
    ) {
      throw new Error("请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片。");
    }
    const form = new FormData();
    const extension =
      file.type === "image/png"
        ? "png"
        : file.type === "image/webp"
          ? "webp"
          : "jpg";
    form.append("image", file, `portrait.${extension}`);
    if (sourceAgeValue !== undefined)
      form.append("source_age", String(finite(sourceAgeValue, "源年龄", 20, 70)));
    const data = record(
      await this.request(
        "/api/reconstruct",
        { method: "POST", body: form },
        signal,
      ),
      "重建结果",
    );
    const result: Reconstruction = {
      mesh_id: meshId(data.mesh_id),
      topology_id: meshId(data.topology_id),
      asset_mode: data.asset_mode as Reconstruction["asset_mode"],
      capabilities: { age_morph: false, age_texture: false },
      source_age: sourceAge(data.source_age),
      shape: vector(data.shape, "形状参数"),
      expr: vector(data.expr, "表情参数"),
      pose: pose(data.pose),
    };
    if (data.asset_mode !== "static" && data.asset_mode !== "age_morph")
      throw new Error("重建结果缺少有效资产模式，请检查 API 1.2 契约。");
    const flags = record(data.capabilities, "结果能力");
    if (typeof flags.age_morph !== "boolean" || typeof flags.age_texture !== "boolean")
      throw new Error("结果能力必须提供 age_morph 和 age_texture 布尔值。");
    result.capabilities = { age_morph: flags.age_morph, age_texture: flags.age_texture };
    if ((data.asset_mode === "age_morph") !== flags.age_morph)
      throw new Error("资产模式与年龄形变能力不一致。");
    if ((flags.age_morph || flags.age_texture) && result.source_age.value === null)
      throw new Error("年龄能力必须有已知源年龄，不能使用默认年龄代替。");
    if (data.texture_url !== undefined && data.texture_url !== null) {
      result.texture_url = this.safeAssetUrl(
        boundedString(data.texture_url, "纹理地址", 2048),
      );
    }
    if (flags.age_texture && !result.texture_url)
      throw new Error("年龄纹理能力需要提供基础纹理资产。");
    return result;
  }

  async aging(
    id: string,
    age: number,
    signal?: AbortSignal,
  ): Promise<AgingResult> {
    meshId(id);
    finite(age, "目标年龄", 20, 70);
    const data = record(
      await this.request(
        "/api/aging",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mesh_id: id, age }),
        },
        signal,
      ),
      "年龄生成结果",
    );
    const result: AgingResult = {
      shape_aged: vector(data.shape_aged, "年龄形状参数"),
    };
    if (data.texture_url !== undefined && data.texture_url !== null) {
      result.texture_url = this.safeAssetUrl(
        boundedString(data.texture_url, "纹理地址", 2048),
      );
    }
    return result;
  }

  private async request(
    path: string,
    init: RequestInit = {},
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (signal?.aborted) throw cancelled();
    const controller = new AbortController();
    let timedOut = false;
    const timer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT);
    const abort = (): void => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
      });
      const text = await readLimitedText(response, MAX_JSON_BYTES);
      let data: unknown;
      try {
        data = JSON.parse(text);
      } catch {
        if (!response.ok)
          throw new Error(
            `本地服务请求失败（HTTP ${response.status}）。请查看后端日志。`,
          );
        throw new Error("本地服务未返回有效 JSON，请检查服务地址与接口版本。");
      }
      if (!response.ok) {
        const detail =
          typeof data === "object" && data !== null && "detail" in data
            ? data.detail
            : undefined;
        const explanation =
          typeof detail === "string"
            ? `：${detail.slice(0, 300)}`
            : "。请查看后端日志。";
        throw new Error(
          `本地服务请求失败（HTTP ${response.status}）${explanation}`,
        );
      }
      return data;
    } catch (error) {
      if (timedOut)
        throw new Error("本地服务在 30 秒内未响应，请检查模型是否就绪后重试。");
      if (signal?.aborted) throw cancelled();
      if (error instanceof TypeError)
        throw new Error(
          "无法连接本地服务，请确认后端已启动、地址正确并允许当前页面跨域访问。",
        );
      throw error;
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
}

async function readLimitedText(
  response: Response,
  limit: number,
): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("本地服务返回了空响应。");
  const decoder = new TextDecoder();
  let size = 0;
  let text = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new Error("本地服务响应过大，已停止读取。");
      }
      text += decoder.decode(chunk.value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}

function videoBlob(
  video: HTMLVideoElement,
  maxSide: number,
  quality: number,
): Promise<{ blob: Blob; size: FrameSize }> {
  if (
    video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
    !video.videoWidth ||
    !video.videoHeight
  ) {
    return Promise.reject(new Error("摄像头画面尚未就绪，请稍后再试。"));
  }
  const scale = Math.min(
    1,
    maxSide / Math.max(video.videoWidth, video.videoHeight),
  );
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  const context = canvas.getContext("2d");
  if (!context) return Promise.reject(new Error("浏览器无法创建图像画布。"));
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  // CSS mirrors only the local preview; drawImage submits the original pixels.
  const size: FrameSize = [canvas.width, canvas.height];
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) =>
        blob ? resolve({ blob, size }) : reject(new Error("画面编码失败，请重新拍摄。")),
      "image/jpeg",
      quality,
    );
  });
}

export class CameraController {
  private stream: MediaStream | null = null;
  private generation = 0;
  private pending: Promise<void> | null = null;
  private readonly trackListeners = new Map<MediaStreamTrack, () => void>();

  constructor(
    private readonly video: HTMLVideoElement,
    private readonly onEnded?: () => void,
  ) {}

  get active(): boolean {
    return (
      this.stream
        ?.getVideoTracks()
        .some((track) => track.readyState === "live") ?? false
    );
  }

  start(): Promise<void> {
    if (this.active) return Promise.resolve();
    if (this.pending) return this.pending;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      return Promise.reject(
        new Error(
          "摄像头需要在 localhost 或 HTTPS 页面中使用，请检查浏览器支持。",
        ),
      );
    }
    const generation = ++this.generation;
    const operation = this.open(generation);
    this.pending = operation;
    void operation
      .finally(() => {
        if (this.pending === operation) this.pending = null;
      })
      .catch(() => {});
    return operation;
  }

  private async open(generation: number): Promise<void> {
    let acquired: MediaStream | null = null;
    try {
      acquired = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
      if (generation !== this.generation) {
        acquired.getTracks().forEach((track) => track.stop());
        throw cancelled();
      }
      this.stream = acquired;
      const ended = (): void => {
        if (generation !== this.generation || this.stream !== acquired) return;
        this.stop();
        this.onEnded?.();
      };
      acquired.getVideoTracks().forEach((track) => {
        track.addEventListener("ended", ended);
        this.trackListeners.set(track, ended);
      });
      if (!this.active) {
        ended();
        throw cancelled();
      }
      this.video.srcObject = acquired;
      this.video.muted = true;
      this.video.playsInline = true;
      await this.video.play();
      if (generation !== this.generation) {
        acquired.getTracks().forEach((track) => track.stop());
        throw cancelled();
      }
    } catch (error) {
      acquired?.getTracks().forEach((track) => track.stop());
      if (generation === this.generation) {
        this.removeTrackListeners();
        this.stream = null;
        this.video.srcObject = null;
      }
      if (generation !== this.generation) throw cancelled();
      const name = error instanceof DOMException ? error.name : "";
      if (name === "NotAllowedError" || name === "SecurityError")
        throw new Error("摄像头权限未获允许，请在浏览器地址栏授权后重试。");
      if (name === "NotFoundError")
        throw new Error("没有找到摄像头，请连接摄像头或上传照片。");
      if (name === "NotReadableError")
        throw new Error("摄像头无法打开，可能被其他应用占用。");
      throw new Error(messageOf(error, "摄像头启动失败，请尝试上传照片。"));
    }
  }

  stop(): void {
    ++this.generation;
    this.pending = null;
    this.removeTrackListeners();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.video.pause();
    this.video.srcObject = null;
  }

  private removeTrackListeners(): void {
    this.trackListeners.forEach((listener, track) =>
      track.removeEventListener("ended", listener),
    );
    this.trackListeners.clear();
  }

  capture(): Promise<Blob> {
    if (!this.active) return Promise.reject(new Error("请先打开摄像头。"));
    return videoBlob(this.video, 1280, 0.92).then(({ blob }) => blob);
  }
}

function faceState(data: Record<string, unknown>): FaceState {
  const seq = finite(data.seq, "帧序号", 0, Number.MAX_SAFE_INTEGER);
  if (!Number.isSafeInteger(seq)) throw new Error("帧序号必须是非负整数。");
  const box = vector(data.bbox, "人脸框", 4);
  box.forEach((item) => finite(item, "人脸框", 0, 16384));
  if (box[2] === 0 || box[3] === 0) throw new Error("人脸框尺寸必须大于零。");
  if (!Array.isArray(data.landmarks) || data.landmarks.length !== 5)
    throw new Error("实时结果必须包含 5 个关键点。");
  const landmarks = data.landmarks.map((point): [number, number] => {
    const pair = vector(point, "关键点", 2);
    return [
      finite(pair[0], "关键点", -16384, 16384),
      finite(pair[1], "关键点", -16384, 16384),
    ];
  });
  const result: FaceState = {
    type: "face_state",
    seq,
    ts: finite(data.ts, "帧时间", 0, Number.MAX_SAFE_INTEGER),
    bbox: [box[0]!, box[1]!, box[2]!, box[3]!],
    landmarks,
    pose: pose(data.pose),
    conf: finite(data.conf, "人脸置信度", 0, 1),
  };
  if (data.shape !== undefined) result.shape = vector(data.shape, "形状参数");
  if (data.expr !== undefined) result.expr = vector(data.expr, "表情参数");
  return result;
}

function hasLiveVideo(video: HTMLVideoElement): boolean {
  return (
    video.srcObject instanceof MediaStream &&
    video.srcObject
      .getVideoTracks()
      .some((track) => track.readyState === "live")
  );
}

/** JPEG input is throttled; each response acknowledges one outstanding input frame. */
export class FrameStream {
  private socket: WebSocket | null = null;
  private timer: number | null = null;
  private responseTimer: number | null = null;
  private pending = false;
  private generation = 0;
  private lastSequence = -1;
  private sentSequence = 0;
  private pendingSequence: number | null = null;
  private pendingSize: FrameSize | null = null;

  constructor(
    private readonly api: LocalApi,
    private readonly video: HTMLVideoElement,
    private readonly callbacks: FrameCallbacks,
  ) {}

  start(): void {
    this.stop();
    if (!hasLiveVideo(this.video)) {
      this.callbacks.onError?.("请先打开摄像头，再连接实时检测。");
      return;
    }
    const generation = this.generation;
    let socket: WebSocket;
    try {
      socket = new WebSocket(this.api.websocketUrl());
    } catch {
      this.callbacks.onError?.("实时连接建立失败，请检查本地服务地址。");
      return;
    }
    this.socket = socket;
    this.lastSequence = -1;
    this.sentSequence = 0;
    this.callbacks.onStatus?.("正在连接本地实时服务…");
    this.responseTimer = window.setTimeout(
      () => this.fail("实时连接超时，请检查后端后手动重试。"),
      8_000,
    );
    socket.onopen = () => {
      if (generation !== this.generation) return;
      this.acknowledge();
      this.callbacks.onStatus?.("实时服务已连接，正在等待检测结果。");
      this.timer = window.setInterval(() => {
        void this.sendFrame(generation);
      }, 100);
      void this.sendFrame(generation);
    };
    socket.onmessage = (event: MessageEvent<unknown>) => {
      if (generation !== this.generation) return;
      try {
        this.receive(event.data);
      } catch (error) {
        this.fail(messageOf(error, "实时服务返回了无效数据。"));
      }
    };
    socket.onerror = () => {
      if (generation === this.generation)
        this.fail("实时连接失败，请确认后端已启动并支持 /ws/frame。");
    };
    socket.onclose = () => {
      if (generation === this.generation)
        this.fail("实时服务已断开，点击连接可手动重试。");
    };
  }

  private async sendFrame(generation: number): Promise<void> {
    if (generation !== this.generation) return;
    if (!hasLiveVideo(this.video)) {
      this.fail("摄像头已断开，实时检测已停止。");
      return;
    }
    if (
      this.pending ||
      this.socket?.readyState !== WebSocket.OPEN ||
      this.socket.bufferedAmount > 0
    )
      return;
    this.pending = true;
    this.responseTimer = window.setTimeout(
      () => this.fail("摄像头画面在 8 秒内未完成编码，连接已停止，请手动重试。"),
      8_000,
    );
    try {
      const frame = await videoBlob(this.video, 640, 0.7);
      if (
        generation !== this.generation ||
        this.socket?.readyState !== WebSocket.OPEN
      )
        return;
      if (!hasLiveVideo(this.video)) {
        this.fail("摄像头已断开，实时检测已停止。");
        return;
      }
      this.pendingSequence = ++this.sentSequence;
      this.pendingSize = frame.size;
      this.socket.send(frame.blob);
      if (this.responseTimer !== null) window.clearTimeout(this.responseTimer);
      this.responseTimer = window.setTimeout(
        () =>
          this.fail("实时服务 8 秒未返回检测结果，连接已停止，请手动重试。"),
        8_000,
      );
    } catch (error) {
      if (generation === this.generation)
        this.fail(messageOf(error, "摄像头画面发送失败。"));
    }
  }

  private receive(raw: unknown): void {
    if (typeof raw !== "string")
      throw new Error("实时服务应返回 JSON 文本消息。");
    if (new TextEncoder().encode(raw).byteLength > MAX_FRAME_MESSAGE_BYTES)
      throw new Error("实时返回数据超过 1 KB，已停止连接。");
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error("实时服务返回了无效 JSON。");
    }
    const data = record(parsed, "实时消息");
    if (data.type === "face_state") {
      const state = faceState(data);
      if (!this.matchesPending(state.seq)) return;
      const size = this.pendingSize!;
      if (
        state.bbox[0] + state.bbox[2] > size[0] + 0.001 ||
        state.bbox[1] + state.bbox[3] > size[1] + 0.001
      )
        throw new Error("人脸框超出所提交图像的尺寸。");
      this.lastSequence = state.seq;
      this.acknowledge();
      this.callbacks.onState(state, size);
      return;
    }
    if (data.type === "error") {
      const code = boundedString(data.code, "实时错误代码", 40);
      const message = boundedString(data.msg, "实时错误说明", 300);
      const seq = finite(data.seq, "帧序号", 1, Number.MAX_SAFE_INTEGER);
      if (!Number.isSafeInteger(seq)) throw new Error("帧序号必须是正整数。");
      if (!this.matchesPending(seq)) return;
      this.lastSequence = seq;
      this.acknowledge();
      if (code === "NO_FACE" || code === "MULTI_FACE" || code === "BUSY") {
        this.callbacks.onRecoverableError?.(code, message);
        this.callbacks.onStatus?.(message);
      } else this.fail(message);
      return;
    }
    if (data.type === "status") {
      const device = boundedString(data.device, "推理设备", 80);
      const fps =
        data.fps === undefined
          ? ""
          : ` · ${finite(data.fps, "推理帧率", 0, 10000).toFixed(1)} FPS`;
      this.callbacks.onStatus?.(`本地推理设备 ${device}${fps}`);
      return;
    }
    throw new Error("实时服务返回了不支持的消息类型。");
  }

  private acknowledge(): void {
    this.pending = false;
    this.pendingSequence = null;
    this.pendingSize = null;
    if (this.responseTimer !== null) window.clearTimeout(this.responseTimer);
    this.responseTimer = null;
  }

  private matchesPending(seq: number): boolean {
    if (seq <= this.lastSequence) return false;
    if (seq !== this.pendingSequence)
      throw new Error("实时服务回复与当前等待的帧不一致。");
    return true;
  }

  private fail(message: string): void {
    this.stop();
    this.callbacks.onError?.(message);
  }

  stop(): void {
    ++this.generation;
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
    this.acknowledge();
    if (this.socket) {
      const socket = this.socket;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
      )
        socket.close(1000, "client stopped");
    }
    this.socket = null;
  }
}
