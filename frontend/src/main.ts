import "./style.css";
import { FaceViewer } from "./viewer";
import { CameraController, FrameStream, LocalApi } from "./services";
import type { Capabilities, FaceState, Health, Reconstruction } from "./contracts";
import { mirroredPose, type FrameSize } from "./realtime";

// The markup lives in index.html; this module binds behavior to its element ids.
const el = <T extends HTMLElement = HTMLElement>(id: string): T =>
  document.getElementById(id) as T;
const button = (id: string): HTMLButtonElement => el<HTMLButtonElement>(id);
const input = (id: string): HTMLInputElement => el<HTMLInputElement>(id);
const on = (id: string, event: string, handler: EventListener): void =>
  el(id).addEventListener(event, handler);
const video = el<HTMLVideoElement>("camera-video");
const camera = new CameraController(video, () => {
  stopCamera();
  notify("摄像头已断开，请重新连接设备。", true);
});
let viewer: FaceViewer | undefined;
let api: LocalApi | undefined;
let health: Health | undefined;
let stream: FrameStream | undefined;
let source: Blob | undefined;
let sourceUrl: string | undefined;
let meshId: string | undefined;
let reconstruction: Reconstruction | undefined;
let sourceVersion = 0;
let taskVersion = 0;
let connectionVersion = 0;
let healthTimer: number | undefined;
let healthDeadlineTimer: number | undefined;
let healthOperation: AbortController | undefined;
let busy = false;
let cameraStarting = false;
let age = 30;
let compare = false;
let rotating = false;
let grid = true;
let textureBusy = false;
let exporting = false;
let textureAge: number | undefined;
let operation: AbortController | undefined;
let textureOperation: AbortController | undefined;
let toastTimer = 0;
let currentMode: "solid" | "wireframe" | "points" = "solid";
const identityPose = { R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, 0] };

function notify(message: string, error = false): void {
  window.clearTimeout(toastTimer);
  el("toast-text").textContent = message;
  el("toast").classList.toggle("error", error);
  el("toast").hidden = false;
  toastTimer = window.setTimeout(
    () => {
      el("toast").hidden = true;
    },
    error ? 9000 : 5500,
  );
}
function message(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请重试。";
}
function isCancelled(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
function setPressed(id: string, active: boolean): void {
  button(id).setAttribute("aria-pressed", String(active));
}

function supports(capability: keyof Capabilities): boolean {
  return Boolean(api && health?.capabilities?.[capability] === true);
}

function canMorph(): boolean {
  return !meshId || Boolean(reconstruction?.capabilities.age_morph && supports("age_morph"));
}

function canTexture(): boolean {
  return Boolean(meshId && reconstruction?.capabilities.age_texture && supports("age_texture"));
}

function canAdjustAge(): boolean {
  return canMorph() || canTexture();
}

function validSourceAge(): boolean {
  return input("source-age").validity.valid;
}

function showSourceAgeValidity(): void {
  const valid = validSourceAge();
  input("source-age").setAttribute("aria-invalid", String(!valid));
  el("source-age-hint").textContent = valid ? "" : "请输入 20–70 岁，或留空表示未知";
}

function updateAgeDisplay(): void {
  const staticOnly = meshId && reconstruction?.asset_mode === "static" && !canTexture();
  const displayAge = staticOnly ? reconstruction?.source_age.value : age;
  input("age-slider").step = meshId && reconstruction?.source_age.value != null && !Number.isInteger(reconstruction.source_age.value) ? "any" : "1";
  input("age-slider").value = String(age);
  input("age-slider").setAttribute("aria-valuetext", displayAge == null ? "源年龄未知" : `${displayAge} 岁`);
  el<HTMLOutputElement>("age-output").value = displayAge == null ? "未知" : String(displayAge);
  el("age-unit").hidden = displayAge == null;
  el("compare-age").textContent = String(age);
  el("compare-source-age").textContent = meshId
    ? reconstruction?.source_age.value == null ? "未知" : String(reconstruction.source_age.value)
    : "30";
  el("age-description").textContent = !meshId || canMorph()
    ? ""
    : canTexture()
      ? reconstruction?.asset_mode === "static"
        ? "仅生成年龄纹理，三维形状保持原始重建"
        : "仅生成年龄纹理，三维形状保持当前状态"
      : "年龄变换不可用";
}

function showHealth(status: Health): void {
  el("health-status").textContent =
    `连接成功 · ${status.device} · v${status.version} · API ${status.api_version ?? "未知"}\n` +
    (status.capabilities
      ? `能力：${Object.entries(status.capabilities).map(([name, ready]) => `${name}=${ready ? "可用" : "不可用"}`).join("；")}\n`
      : "能力状态未知，请检查 API 版本（需要 1.1 或 1.2）与 capabilities 字段。推理操作已禁用。\n") +
    (Object.entries(status.models).map(([name, model]) =>
      `${name}: state=${model.state} · backend=${model.backend ?? "未配置"} · provider=${model.provider ?? "未配置"} · ${model.detail || "无补充说明"}`,
    ).join("\n") || "模型状态：未提供，请检查后端状态。");
}

/** Idle source status: only what blocks reconstruction and is not already visible. */
function showSourceStatus(): void {
  el("source-status").textContent = !api
    ? source ? "未连接本地服务" : ""
    : !health?.capabilities
      ? "重建能力未知，需要 API 1.1 或 1.2"
      : !supports("reconstruction")
        ? "三维重建能力不可用"
        : "";
}

function stopHealthRefresh(): void {
  window.clearTimeout(healthTimer);
  window.clearTimeout(healthDeadlineTimer);
  healthTimer = undefined;
  healthDeadlineTimer = undefined;
  healthOperation?.abort();
  healthOperation = undefined;
}

/** Refresh only a loading connection, with one in-flight request and a 30-second total budget. */
function refreshLoadingHealth(client: LocalApi, version: number): void {
  const loading = (): boolean => Boolean(health && Object.values(health.models).some((model) => model.state === "loading"));
  if (!loading()) return;
  healthDeadlineTimer = window.setTimeout(() => {
    if (version !== connectionVersion) return;
    stopHealthRefresh();
    el("health-status").textContent += "\n模型仍在加载，自动刷新已结束；可重新检查连接获取最新状态。";
  }, 30_000);
  const schedule = (): void => {
    healthTimer = window.setTimeout(() => {
      healthTimer = undefined;
      const controller = new AbortController();
      healthOperation = controller;
      void client.health(controller.signal).then((status) => {
        if (version !== connectionVersion || controller.signal.aborted) return;
        health = status;
        showHealth(status);
        if (!meshId && !busy) showSourceStatus();
        refreshActions();
        if (loading()) schedule();
        else stopHealthRefresh();
      }).catch((error: unknown) => {
        if (version !== connectionVersion || controller.signal.aborted) return;
        stopHealthRefresh();
        health = undefined;
        el("health-status").textContent = `服务状态刷新失败：${message(error)} 请重新检查连接。`;
        if (!meshId && !busy) showSourceStatus();
        refreshActions();
      }).finally(() => {
        if (healthOperation === controller) healthOperation = undefined;
      });
    }, 500);
  };
  schedule();
}

function refreshActions(): void {
  if (stream && !supports("realtime")) stopStream();
  button("reconstruct").disabled =
    !source || !supports("reconstruction") || !input("photo-consent").checked || !validSourceAge() || busy || !viewer;
  input("source-age").disabled = !source || busy;
  button("reconstruct").setAttribute("aria-busy", String(busy));
  button("reconstruct").textContent = busy ? "正在重建…" : "开始三维重建";
  button("cancel-reconstruct").hidden = !busy;
  // Show a control only once its prerequisite exists, instead of explaining why it is off.
  el("source-age-field").hidden = !source;
  button("stream-toggle").hidden = !api;
  el("texture-group").hidden = !meshId;
  button("load-demo").hidden = !meshId || busy;
  button("apply-texture").disabled =
    !canTexture() || textureBusy || busy || !viewer;
  button("apply-texture").setAttribute("aria-busy", String(textureBusy));
  button("export-glb").disabled = !viewer || busy || exporting;
  button("export-png").disabled = !viewer || busy || exporting;
  button("camera-capture").disabled = !camera.active || busy;
  button("stream-toggle").disabled =
    !camera.active || !supports("realtime") || !input("photo-consent").checked || busy;
  button("camera-toggle").disabled = cameraStarting;
  input("age-slider").disabled = !canAdjustAge() || busy || !viewer;
  button("age-reset").disabled = !canAdjustAge() || busy || !viewer;
  document.querySelectorAll<HTMLButtonElement>("[data-age]").forEach((item) => {
    item.disabled = !canAdjustAge() || busy || !viewer;
  });
  button("compare-toggle").disabled = !canMorph() || busy || !viewer;
  if (!canMorph() && compare) {
    compare = false;
    viewer?.setCompare(false);
    setPressed("compare-toggle", false);
    el("comparison-labels").hidden = true;
  }
  updateAgeDisplay();
  if (api && !supports("age_texture"))
    el("texture-hint").textContent = health?.capabilities ? "年龄纹理能力不可用" : "年龄纹理能力未知";
  else if (meshId && !reconstruction?.capabilities.age_texture)
    el("texture-hint").textContent = "此重建不支持年龄纹理";
  if (api && !supports("realtime"))
    el("stream-status").textContent = health?.capabilities ? "实时检测能力不可用" : "实时检测能力未知";
}

function markDemo(): void {
  meshId = undefined;
  reconstruction = undefined;
  age = 30;
  viewer?.setAge(30);
  el("model-badge").textContent = "演示模型";
  el("model-badge").classList.remove("real");
  el("info-source").textContent = "";
  el("info-source").removeAttribute("title");
  el("viewer").dataset.source = "demo";
  el("texture-hint").textContent = "";
}
function cancelTask(): void {
  taskVersion++;
  operation?.abort();
  operation = undefined;
  textureOperation?.abort();
  textureOperation = undefined;
  textureBusy = false;
  textureAge = undefined;
  busy = false;
}
function resetDemo(): void {
  cancelTask();
  viewer?.loadDemo();
  markDemo();
  refreshActions();
}

function createViewer(): void {
  viewer?.dispose();
  viewer = undefined;
  el("viewer-fallback").hidden = true;
  try {
    viewer = new FaceViewer(el("viewer"), {
      onStats(stats) {
        // Machine-readable render state for tests and agents; not shown on screen.
        el("viewer").dataset.vertices = String(stats.vertices);
        el("viewer").dataset.triangles = String(stats.triangles);
      },
      onError(error) {
        el("viewer-error").textContent = error;
        el("viewer-fallback").hidden = false;
      },
      onRestore() {
        el("viewer-fallback").hidden = true;
      },
    });
    viewer.setAge(age);
    viewer.setMode(currentMode);
    viewer.setCompare(compare);
    viewer.setBackground(grid);
    viewer.setAutoRotate(rotating);
    viewer.setLighting(
      el<HTMLSelectElement>("lighting").value as "studio" | "soft" | "dramatic",
    );
    markDemo();
  } catch (error) {
    el("viewer-error").textContent =
      `WebGL 2 初始化失败。${message(error)} 请检查浏览器硬件加速，或使用 Chrome / Edge 重试。`;
    el("viewer-fallback").hidden = false;
  }
  refreshActions();
}

function changeAge(value: number): void {
  if (!canAdjustAge() || busy || !Number.isFinite(value)) return;
  age = Math.max(20, Math.min(70, value));
  updateAgeDisplay();
  if (canMorph()) viewer?.setAge(age);
  if (textureAge !== undefined || textureBusy) {
    textureOperation?.abort();
    textureOperation = undefined;
    textureBusy = false;
    textureAge = undefined;
    void viewer?.setTexture(null);
    el("texture-hint").textContent = "";
    refreshActions();
  }
}
on("age-slider", "input", () => changeAge(Number(input("age-slider").value)));
document
  .querySelectorAll<HTMLButtonElement>("[data-age]")
  .forEach((item) =>
    item.addEventListener("click", () => changeAge(Number(item.dataset.age))),
  );
on("age-reset", "click", () => changeAge(reconstruction?.source_age.value ?? 30));
document.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((item) =>
  item.addEventListener("click", () => {
    currentMode = item.dataset.mode as typeof currentMode;
    viewer?.setMode(currentMode);
    document
      .querySelectorAll<HTMLButtonElement>("[data-mode]")
      .forEach((other) => other.setAttribute("aria-pressed", String(other === item)));
  }),
);
document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((item) =>
  item.addEventListener("click", () => {
    viewer?.setView(item.dataset.view as "front" | "side" | "three-quarter");
    document
      .querySelectorAll<HTMLButtonElement>("[data-view]")
      .forEach((other) => other.setAttribute("aria-pressed", String(other === item)));
  }),
);
on("lighting", "change", () =>
  viewer?.setLighting(
    el<HTMLSelectElement>("lighting").value as "studio" | "soft" | "dramatic",
  ),
);
on("grid-toggle", "click", () => {
  grid = !grid;
  viewer?.setBackground(grid);
  setPressed("grid-toggle", grid);
});
on("rotate-toggle", "click", () => {
  rotating = !rotating;
  viewer?.setAutoRotate(rotating);
  setPressed("rotate-toggle", rotating);
});
on("compare-toggle", "click", () => {
  if (!canMorph() || busy || !viewer) return;
  compare = !compare;
  viewer?.setCompare(compare);
  setPressed("compare-toggle", compare);
  el("comparison-labels").hidden = !compare;
});
on("viewer-retry", "click", () => {
  cancelTask();
  createViewer();
});
on("load-demo", "click", () => {
  stopStream();
  resetDemo();
  changeAge(30);
  showSourceStatus();
});

function clearPhoto(): void {
  sourceVersion++;
  source = undefined;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = undefined;
  el<HTMLImageElement>("source-image").removeAttribute("src");
  input("photo-input").value = "";
  el("photo-preview").hidden = true;
  button("upload-trigger").hidden = false;
  input("photo-consent").checked = false;
  input("source-age").value = "";
  showSourceAgeValidity();
  resetDemo();
  showSourceStatus();
}
async function acceptPhoto(blob: Blob): Promise<void> {
  const version = ++sourceVersion;
  if (
    !["image/jpeg", "image/png", "image/webp"].includes(blob.type) ||
    !blob.size ||
    blob.size > 10 * 1024 * 1024
  ) {
    notify("请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片。", true);
    return;
  }
  try {
    const bitmap = await createImageBitmap(blob);
    const invalid =
      !bitmap.width ||
      !bitmap.height ||
      bitmap.width * bitmap.height > 16_000_000;
    bitmap.close();
    if (invalid)
      throw new Error("图片像素过大，请缩小到 1600 万像素以内再上传。");
    if (version !== sourceVersion) return;
    stopStream();
    resetDemo();
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    sourceUrl = URL.createObjectURL(blob);
    source = blob;
    input("photo-consent").checked = false;
    input("source-age").value = "";
    showSourceAgeValidity();
    el<HTMLImageElement>("source-image").src = sourceUrl;
    el("photo-preview").hidden = false;
    button("upload-trigger").hidden = true;
    showSourceStatus();
    refreshActions();
  } catch (error) {
    if (version === sourceVersion)
      notify(
        error instanceof DOMException
          ? "无法读取这张图片，请检查文件是否损坏。"
          : message(error),
        true,
      );
  }
}
on("upload-trigger", "click", () => input("photo-input").click());
on("photo-input", "change", () => {
  const file = input("photo-input").files?.[0];
  if (file) void acceptPhoto(file);
  input("photo-input").value = "";
});
on("photo-remove", "click", clearPhoto);
for (const event of ["dragenter", "dragover"])
  on("photo-area", event, (e) => {
    e.preventDefault();
    button("upload-trigger").classList.add("dragging");
  });
on("photo-area", "dragleave", () =>
  button("upload-trigger").classList.remove("dragging"),
);
on("photo-area", "drop", (event) => {
  event.preventDefault();
  button("upload-trigger").classList.remove("dragging");
  const files = (event as DragEvent).dataTransfer?.files;
  if (!files?.length) return;
  if (files.length > 1) {
    notify("请一次选择一张人像照片。", true);
    return;
  }
  void acceptPhoto(files[0]);
});
on("photo-consent", "change", () => {
  if (!input("photo-consent").checked) stopStream();
  refreshActions();
});
on("source-age", "input", () => {
  showSourceAgeValidity();
  refreshActions();
});

function switchSource(useCamera: boolean): void {
  el("photo-area").hidden = useCamera;
  el("camera-area").hidden = !useCamera;
  setPressed("photo-tab", !useCamera);
  setPressed("camera-tab", useCamera);
  if (!useCamera) stopCamera();
}
function stopStream(): void {
  stream?.stop();
  stream = undefined;
  button("stream-toggle").textContent = "连接实时检测";
  el("stream-status").textContent = "";
  clearDetection();
}
function stopCamera(): void {
  stopStream();
  camera.stop();
  cameraStarting = false;
  button("camera-toggle").textContent = "开启摄像头";
  el("camera-placeholder").hidden = false;
  refreshActions();
}
on("photo-tab", "click", () => switchSource(false));
on("camera-tab", "click", () => switchSource(true));
on("camera-toggle", "click", () => {
  if (camera.active) {
    stopCamera();
    return;
  }
  cameraStarting = true;
  button("camera-toggle").textContent = "正在等待授权…";
  refreshActions();
  void camera
    .start()
    .then(() => {
      if (!camera.active) return;
      el("camera-placeholder").hidden = true;
      button("camera-toggle").textContent = "关闭摄像头";
    })
    .catch((error: unknown) => {
      if (!isCancelled(error)) notify(message(error), true);
      button("camera-toggle").textContent = "开启摄像头";
    })
    .finally(() => {
      cameraStarting = false;
      refreshActions();
    });
});
on("camera-capture", "click", () => {
  void camera
    .capture()
    .then(async (blob) => {
      await acceptPhoto(blob);
      switchSource(false);
    })
    .catch((error: unknown) => notify(message(error), true));
});
function clearDetection(): void {
  const canvas = el<HTMLCanvasElement>("camera-overlay");
  canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
  viewer?.setPose(identityPose);
}
function drawDetection(state: FaceState, size: FrameSize): void {
  const canvas = el<HTMLCanvasElement>("camera-overlay");
  // Keep the actual submitted size even if the camera changed resolution meanwhile.
  [canvas.width, canvas.height] = size;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "#35d3c0";
  context.lineWidth = 2;
  context.strokeRect(...state.bbox);
  context.fillStyle = "#e8a04c";
  state.landmarks.forEach(([x, y]) => {
    context.beginPath();
    context.arc(x, y, 3, 0, Math.PI * 2);
    context.fill();
  });
  viewer?.setPose(mirroredPose(state.pose));
  el("stream-status").textContent =
    `实时检测 · 置信度 ${(state.conf * 100).toFixed(1)}% · 帧 ${state.seq}`;
}
on("stream-toggle", "click", () => {
  if (stream) {
    stopStream();
    return;
  }
  if (!api || !supports("realtime") || !camera.active || !input("photo-consent").checked) return;
  stream = new FrameStream(api, video, {
    onState: drawDetection,
    onRecoverableError: () => clearDetection(),
    onStatus: (status) => {
      el("stream-status").textContent = status;
    },
    onError: (error) => {
      stopStream();
      el("stream-status").textContent = error;
      notify(error, true);
    },
  });
  button("stream-toggle").textContent = "停止实时检测";
  stream.start();
});

on("reconstruct", "click", () => {
  if (!api || !supports("reconstruction") || !source || !input("photo-consent").checked || !validSourceAge() || !viewer || busy)
    return;
  stopStream();
  cancelTask();
  const version = taskVersion;
  const client = api;
  const file = source;
  const sourceAge = input("source-age").value === "" ? undefined : input("source-age").valueAsNumber;
  operation = new AbortController();
  const signal = operation.signal;
  busy = true;
  el("source-status").textContent = "";
  refreshActions();
  void (async () => {
    try {
      const result = await client.reconstruct(file, signal, sourceAge);
      if (version !== taskVersion || signal.aborted) return;
      el("source-status").textContent = "正在加载三维模型…";
      await viewer!.loadModel(client.assetUrl(result.mesh_id), result);
      if (version !== taskVersion || signal.aborted) return;
      meshId = result.mesh_id;
      reconstruction = result;
      if (result.source_age.value !== null) age = result.source_age.value;
      el("model-badge").textContent = "本地重建";
      el("model-badge").classList.add("real");
      el("info-source").textContent = meshId;
      el("info-source").title = meshId;
      el("viewer").dataset.source = "reconstruction";
      el("texture-hint").textContent = "";
      updateAgeDisplay();
      if (canMorph()) viewer!.setAge(age);
      let textureWarning: string | undefined;
      if (result.texture_url) {
        try {
          await viewer!.setTexture(result.texture_url, true);
        } catch (error) {
          textureWarning = `模型已加载，基础纹理未载入：${message(error)}`;
        }
      }
      if (version !== taskVersion) return;
      el("source-status").textContent =
        result.asset_mode === "static"
          ? canTexture() ? "原始重建，仅年龄纹理可用" : "原始重建，年龄变换不可用"
          : canMorph() ? "" : "年龄形变不可用";
      if (textureWarning) notify(textureWarning, true);
    } catch (error) {
      if (version !== taskVersion || isCancelled(error)) return;
      el("source-status").textContent = message(error);
      notify(message(error), true);
    } finally {
      if (version === taskVersion) {
        busy = false;
        operation = undefined;
        refreshActions();
      }
    }
  })();
});
on("cancel-reconstruct", "click", () => {
  resetDemo();
  el("source-status").textContent = "重建已取消";
});
on("apply-texture", "click", () => {
  if (!meshId || !api || !canTexture() || !viewer || textureBusy || busy) return;
  const requestedAge = age;
  const requestedMesh = meshId;
  const client = api;
  const controller = new AbortController();
  textureOperation = controller;
  textureBusy = true;
  el("texture-hint").textContent = `正在生成 ${requestedAge} 岁纹理…`;
  refreshActions();
  void (async () => {
    try {
      const result = await client.aging(
        requestedMesh,
        requestedAge,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestedAge !== age ||
        requestedMesh !== meshId
      )
        return;
      if (!result.texture_url)
        throw new Error("服务返回了年龄参数，但尚未提供年龄纹理。");
      await viewer!.setTexture(result.texture_url, false, requestedAge);
      if (
        controller.signal.aborted ||
        requestedAge !== age ||
        requestedMesh !== meshId
      )
        return;
      textureAge = requestedAge;
      el("texture-hint").textContent = `已应用 ${requestedAge} 岁纹理`;
    } catch (error) {
      if (controller.signal.aborted) return;
      el("texture-hint").textContent = message(error);
      notify(message(error), true);
    } finally {
      if (textureOperation === controller) {
        textureBusy = false;
        textureOperation = undefined;
        refreshActions();
      }
    }
  })();
});

async function exportFile(format: "glb" | "png"): Promise<void> {
  if (!viewer || busy || exporting) return;
  exporting = true;
  const target = button(`export-${format}`);
  refreshActions();
  target.setAttribute("aria-busy", "true");
  try {
    const exportAge = age;
    const provenance = meshId ? "local" : "demo";
    const suffix = reconstruction?.asset_mode === "static" ? "original" : `age${exportAge}`;
    const blob =
      format === "glb" ? await viewer.exportGLB() : await viewer.exportPNG();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `AgeMorph3D-${provenance}-${suffix}.${format}`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  } catch (error) {
    notify(message(error), true);
  } finally {
    exporting = false;
    refreshActions();
    target.setAttribute("aria-busy", "false");
  }
}
on("export-glb", "click", () => {
  void exportFile("glb");
});
on("export-png", "click", () => {
  void exportFile("png");
});
on("toast-close", "click", () => {
  el("toast").hidden = true;
  window.clearTimeout(toastTimer);
});

const settingsDialog = el<HTMLDialogElement>("settings-dialog");
on("settings-open", "click", () => settingsDialog.showModal());
settingsDialog.addEventListener("click", (event) => {
  if (event.target !== settingsDialog) return;
  const r = settingsDialog.getBoundingClientRect();
  if (
    event.clientX < r.left ||
    event.clientX > r.right ||
    event.clientY < r.top ||
    event.clientY > r.bottom
  )
    settingsDialog.close();
});
on("connect-api", "click", () => {
  const version = ++connectionVersion;
  stopHealthRefresh();
  api = undefined;
  health = undefined;
  stopStream();
  resetDemo();
  el("connection-label").textContent = "正在检查本地服务";
  el("connection-dot").classList.remove("connected");
  button("connect-api").disabled = true;
  el("health-status").textContent = "正在检查本地服务…";
  const controller = new AbortController();
  healthOperation = controller;
  void (async () => {
    try {
      const client = new LocalApi(input("api-url").value.trim());
      const status = await client.health(controller.signal);
      if (version !== connectionVersion) return;
      api = client;
      health = status;
      input("api-url").value = client.baseUrl;
      el("connection-label").textContent = "本地服务已连接";
      el("connection-dot").classList.add("connected");
      showHealth(status);
      showSourceStatus();
      refreshLoadingHealth(client, version);
    } catch (error) {
      if (version === connectionVersion) {
        el("connection-label").textContent = "本地演示模式";
        el("health-status").textContent = message(error);
        showSourceStatus();
        notify(message(error), true);
      }
    } finally {
      if (healthOperation === controller) healthOperation = undefined;
      if (version === connectionVersion) {
        button("connect-api").disabled = false;
        refreshActions();
      }
    }
  })();
});
on("disconnect", "click", () => {
  connectionVersion++;
  stopHealthRefresh();
  api = undefined;
  health = undefined;
  stopStream();
  resetDemo();
  button("connect-api").disabled = false;
  el("connection-label").textContent = "本地演示模式";
  el("connection-dot").classList.remove("connected");
  el("health-status").textContent = "当前使用程序化演示模型。";
  showSourceStatus();
  settingsDialog.close();
});

window.addEventListener("pagehide", () => {
  connectionVersion++;
  stopHealthRefresh();
  cancelTask();
  stopCamera();
  viewer?.dispose();
  viewer = undefined;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    if (source) {
      sourceUrl = URL.createObjectURL(source);
      el<HTMLImageElement>("source-image").src = sourceUrl;
    }
    createViewer();
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopCamera();
});

createViewer();
