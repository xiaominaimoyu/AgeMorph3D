import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { createDemoHead } from "./demo-head";
import { getAgeWeights } from "./age";
import { LocalApi } from "./services";
import type { Reconstruction } from "./contracts";
import type { ResearchTextureFrame } from "./research-texture";

export type ModelOptions = Pick<Reconstruction, "asset_mode" | "source_age" | "topology_id"> & Partial<Pick<Reconstruction, "capabilities">>;

type Mode = "solid" | "wireframe" | "points";
type ViewerCallbacks = {
  onStats?: (stats: {
    fps: number;
    vertices: number;
    triangles: number;
  }) => void;
  onError?: (message: string) => void;
  onRestore?: () => void;
};
type MeshBinding = {
  mesh: THREE.Mesh;
  material: THREE.Material | THREE.Material[];
  points: THREE.Points;
  anchors: number[] | null;
};
type ColorMaterial = THREE.MeshStandardMaterial | THREE.MeshBasicMaterial;
type ResearchMaterialState = Pick<ColorMaterial,
  "map" | "transparent" | "alphaTest" | "depthWrite" | "premultipliedAlpha" | "opacity"
>;
const AGES = [20, 45, 70] as const;

function assertTextureUv(mesh: THREE.Mesh, channel = 0): void {
  const positions = mesh.geometry.getAttribute("position");
  const uv = mesh.geometry.getAttribute(channel === 0 ? "uv" : `uv${channel}`);
  if (!positions || !uv || uv.itemSize !== 2 || uv.count !== positions.count)
    throw new Error("纹理需要与网格顶点对应的 UV 坐标，请重新生成带 UV 的资产。");
  for (let index = 0; index < uv.count; index++)
    if (!Number.isFinite(uv.getX(index)) || !Number.isFinite(uv.getY(index)))
      throw new Error("纹理 UV 包含无效坐标，请重新生成资产。");
}

async function localAsset(
  url: string,
  maxBytes: number,
  signal: AbortSignal,
): Promise<ArrayBuffer> {
  const parsed = new URL(url);
  new LocalApi(parsed.origin).safeAssetUrl(url);
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) controller.abort();
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 30_000);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      credentials: "omit",
      redirect: "error",
      cache: "no-store",
    });
    if (!response.ok)
      throw new Error(`三维资产读取失败（HTTP ${response.status}）。`);
    if (Number(response.headers.get("content-length")) > maxBytes)
      throw new Error("三维资产超过大小限制，请在后端简化后重试。");
    const reader = response.body?.getReader();
    if (!reader) throw new Error("三维资产为空。");
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    let size = 0;
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.byteLength;
        if (size > maxBytes) {
          await reader.cancel();
          throw new Error("三维资产超过大小限制，请在后端简化后重试。");
        }
        chunks.push(chunk.value);
      }
    } finally {
      reader.releaseLock();
    }
    return await new Blob(chunks).arrayBuffer();
  } catch (error) {
    if (timedOut)
      throw new Error("三维资产加载超过 30 秒，请检查本地服务后重试。");
    if (signal.aborted)
      throw new DOMException("资产加载已取消。", "AbortError");
    if (error instanceof TypeError)
      throw new Error(
        "无法读取本地三维资产，请检查服务地址、CORS 与文件是否就绪。",
      );
    throw error;
  } finally {
    window.clearTimeout(timeout);
    signal.removeEventListener("abort", abort);
  }
}

function disposeObject(
  object: THREE.Object3D,
  extraMaterials: THREE.Material[] = [],
  extraTextures: THREE.Texture[] = [],
): void {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>(extraMaterials);
  const textures = new Set<THREE.Texture>(extraTextures);
  object.traverse((node) => {
    if (
      node instanceof THREE.Mesh ||
      node instanceof THREE.Points ||
      node instanceof THREE.LineSegments
    ) {
      geometries.add(node.geometry);
      (Array.isArray(node.material) ? node.material : [node.material]).forEach(
        (material) => materials.add(material),
      );
    }
  });
  materials.forEach((material) => {
    for (const value of Object.values(material))
      if (value instanceof THREE.Texture) textures.add(value);
    material.dispose();
  });
  geometries.forEach((geometry) => geometry.dispose());
  textures.forEach((texture) => {
    texture.dispose();
    if (
      typeof ImageBitmap !== "undefined" &&
      texture.source.data instanceof ImageBitmap
    )
      texture.source.data.close();
  });
}

/** Owns an isolated WebGL viewport, including its model and all GPU resources. */
export class FaceViewer {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(36, 1, 0.05, 100);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly resizeObserver: ResizeObserver;
  private readonly grid: THREE.GridHelper;
  private readonly key = new THREE.DirectionalLight("#d5faff", 3.2);
  private readonly fill = new THREE.DirectionalLight("#5b8cdb", 1.5);
  private readonly rim = new THREE.DirectionalLight("#48e1cd", 3.3);
  private readonly ambient = new THREE.HemisphereLight(
    "#9cbdcb",
    "#1a2635",
    1.9,
  );
  private readonly wireMaterial = new THREE.MeshStandardMaterial({
    color: "#50cebf",
    wireframe: true,
    roughness: 0.6,
    metalness: 0.1,
  });
  private readonly invisibleMaterial = new THREE.MeshBasicMaterial({
    visible: false,
  });
  private readonly pointMaterial = new THREE.PointsMaterial({
    color: "#6de1cf",
    size: 0.012,
    sizeAttenuation: true,
  });
  private model: THREE.Group | null = null;
  private reference: THREE.Group | null = null;
  private bindings: MeshBinding[] = [];
  private referenceBindings: MeshBinding[] = [];
  private originalMaps = new Map<
    THREE.MeshStandardMaterial | THREE.MeshBasicMaterial,
    THREE.Texture | null
  >();
  private readonly originalTextures = new Set<THREE.Texture>();
  private uploadedTexture: THREE.Texture | null = null;
  private readonly researchMaterialStates = new Map<ColorMaterial, ResearchMaterialState>();
  private researchTexture: THREE.CanvasTexture | null = null;
  private researchCanvas: HTMLCanvasElement | null = null;
  private researchTextureAge: { present: boolean; value: unknown } | null = null;
  private age = 30;
  private assetMode: Reconstruction["asset_mode"] = "age_morph";
  private referenceAge: number | null = 30;
  private mode: Mode = "solid";
  private compare = false;
  private disposed = false;
  private lostContext = false;
  private frame = 0;
  private loadVersion = 0;
  private textureVersion = 0;
  private modelRequest: AbortController | undefined;
  private textureRequest: AbortController | undefined;
  private lastFrame = performance.now();
  private statsTime = performance.now();
  private statsFrames = 0;
  private vertexCount = 0;
  private triangleCount = 0;

  constructor(
    private readonly container: HTMLElement,
    private readonly callbacks: ViewerCallbacks = {},
  ) {
    this.scene.background = new THREE.Color("#0a0e1a");
    this.scene.fog = new THREE.Fog("#0a0e1a", 8, 19);
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.domElement.className = "face-canvas";
    this.renderer.domElement.setAttribute(
      "aria-label",
      "可交互的三维人脸模型；拖动旋转，滚轮缩放",
    );
    this.renderer.domElement.setAttribute("role", "img");
    this.renderer.domElement.style.display = "block";
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.renderer.domElement.addEventListener(
      "webglcontextlost",
      this.onContextLost,
    );
    this.renderer.domElement.addEventListener(
      "webglcontextrestored",
      this.onContextRestored,
    );
    container.append(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.minDistance = 2.1;
    this.controls.maxDistance = 9;
    this.controls.maxPolarAngle = Math.PI * 0.78;
    this.controls.minPolarAngle = Math.PI * 0.15;
    this.controls.autoRotateSpeed = 0.65;
    this.key.position.set(3, 4, 5);
    this.fill.position.set(-4, 1, 3);
    this.rim.position.set(1, 3, -4);
    this.scene.add(this.key, this.fill, this.rim, this.ambient);
    this.grid = new THREE.GridHelper(20, 80, "#263947", "#172530");
    this.grid.position.y = -1.47;
    const gridMaterials = Array.isArray(this.grid.material)
      ? this.grid.material
      : [this.grid.material];
    gridMaterials.forEach((material) => {
      material.transparent = true;
      material.opacity = 0.37;
    });
    this.scene.add(this.grid);
    this.resizeObserver = new ResizeObserver(this.resize);
    this.resizeObserver.observe(container);
    this.loadDemo();
    this.resize();
    this.resetView();
    this.frame = requestAnimationFrame(this.animate);
  }

  private readonly onContextLost = (event: Event): void => {
    event.preventDefault();
    this.lostContext = true;
    this.callbacks.onError?.(
      "WebGL 图形上下文丢失。浏览器恢复后将自动重绘；若未恢复，请刷新页面。",
    );
  };

  private readonly onContextRestored = (): void => {
    this.lostContext = false;
    this.resize();
    this.callbacks.onRestore?.();
  };

  private readonly resize = (): void => {
    if (this.disposed) return;
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  };

  private readonly animate = (now: number): void => {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.animate);
    const delta = Math.min((now - this.lastFrame) / 1000, 0.1);
    this.lastFrame = now;
    if (this.lostContext || document.hidden) return;
    this.controls.update(delta);
    this.renderer.render(this.scene, this.camera);
    this.statsFrames++;
    if (now - this.statsTime >= 700) {
      this.callbacks.onStats?.({
        fps: Math.round((this.statsFrames * 1000) / (now - this.statsTime)),
        vertices: this.vertexCount,
        triangles: this.triangleCount,
      });
      this.statsFrames = 0;
      this.statsTime = now;
    }
  };

  private bind(root: THREE.Group): MeshBinding[] {
    const meshes: THREE.Mesh[] = [];
    root.traverse((node) => {
      if (node instanceof THREE.Mesh) meshes.push(node);
    });
    return meshes.map((mesh) => {
      const dictionary = mesh.morphTargetDictionary;
      const anchors =
        dictionary &&
        AGES.every((age) => dictionary[`age_${age}`] !== undefined)
          ? AGES.map((age) => dictionary[`age_${age}`])
          : null;
      const points = new THREE.Points(mesh.geometry, this.pointMaterial);
      points.name = "Viewport_Point_Display";
      points.userData.agemorphDisplayHelper = true;
      points.visible = false;
      points.frustumCulled = false;
      mesh.add(points);
      mesh.frustumCulled = false;
      const material = mesh.material;
      (Array.isArray(material) ? material : [material]).forEach((entry) => {
        if (
          entry instanceof THREE.MeshStandardMaterial ||
          entry instanceof THREE.MeshBasicMaterial
        ) {
          this.originalMaps.set(entry, entry.map);
          if (entry.map) this.originalTextures.add(entry.map);
        }
      });
      return { mesh, material, points, anchors };
    });
  }

  private releaseModel(): void {
    const holder = new THREE.Group();
    if (this.model) holder.add(this.model);
    if (this.reference) holder.add(this.reference);
    const allBindings = [...this.bindings, ...this.referenceBindings];
    const materials = allBindings.flatMap((binding) =>
      Array.isArray(binding.material) ? binding.material : [binding.material],
    );
    const sourceMaterials = new Map(
      allBindings.map((binding) => [binding.mesh, binding.material]),
    );
    // Shared display materials belong to the viewer, not to a loaded asset.
    holder.traverse((node) => {
      if (node instanceof THREE.Mesh) {
        const material = sourceMaterials.get(node);
        if (material) node.material = material;
      }
    });
    allBindings.forEach((binding) => binding.points.removeFromParent());
    this.restoreTexture();
    disposeObject(holder, materials, [...this.originalTextures]);
    this.originalTextures.clear();
    this.model = null;
    this.reference = null;
    this.bindings = [];
    this.referenceBindings = [];
    this.originalMaps.clear();
  }

  private replaceModel(root: THREE.Group): void {
    this.releaseModel();
    this.model = root;
    this.reference = root.clone(true);
    this.reference.name = `${root.name}_Reference`;
    const referenceMaterials = new Map<THREE.Material, THREE.Material>();
    this.reference.traverse((node) => {
      if (!(node instanceof THREE.Mesh)) return;
      const clone = (material: THREE.Material): THREE.Material => {
        if (!referenceMaterials.has(material))
          referenceMaterials.set(material, material.clone());
        return referenceMaterials.get(material)!;
      };
      node.material = Array.isArray(node.material)
        ? node.material.map(clone)
        : clone(node.material);
    });
    this.bindings = this.bind(root);
    this.referenceBindings = this.bind(this.reference);
    this.scene.add(root, this.reference);
    this.vertexCount = this.bindings.reduce(
      (count, binding) =>
        count + binding.mesh.geometry.getAttribute("position").count,
      0,
    );
    this.triangleCount = this.bindings.reduce(
      (count, binding) =>
        count +
        (binding.mesh.geometry.index?.count ??
          binding.mesh.geometry.getAttribute("position").count) /
          3,
      0,
    );
    if (this.assetMode === "age_morph" && this.referenceAge !== null)
      this.applyWeights(this.referenceBindings, this.referenceAge);
    this.setAge(this.age);
    this.setMode(this.mode);
    this.setCompare(this.compare);
  }

  private applyWeights(bindings: MeshBinding[], age: number): void {
    const weights = getAgeWeights(age);
    for (const binding of bindings) {
      if (!binding.anchors || !binding.mesh.morphTargetInfluences) continue;
      binding.mesh.morphTargetInfluences.fill(0);
      binding.anchors.forEach((index, anchor) => {
        binding.mesh.morphTargetInfluences![index] = weights[anchor];
      });
      if (binding.points.morphTargetInfluences)
        binding.points.morphTargetInfluences = [
          ...binding.mesh.morphTargetInfluences,
        ];
    }
  }

  setAge(age: number): void {
    if (this.assetMode === "static") return;
    getAgeWeights(age); // Validate before mutating the currently displayed model.
    this.age = THREE.MathUtils.clamp(age, 20, 70);
    this.applyWeights(this.bindings, this.age);
    if (this.model) this.model.userData.displayAge = this.age;
  }

  setMode(mode: Mode): void {
    this.mode = mode;
    for (const binding of [...this.bindings, ...this.referenceBindings]) {
      binding.mesh.material =
        mode === "solid"
          ? binding.material
          : mode === "wireframe"
            ? this.wireMaterial
            : this.invisibleMaterial;
      binding.points.visible = mode === "points";
    }
  }

  setCompare(enabled: boolean): void {
    enabled = enabled && this.assetMode === "age_morph";
    const changed = this.compare !== enabled;
    this.compare = enabled;
    if (!this.model || !this.reference) return;
    this.reference.visible = enabled;
    this.model.position.set(enabled ? 0.95 : 0, 0, 0);
    this.reference.position.set(-0.95, 0, 0);
    this.model.scale.setScalar(enabled ? 0.77 : 1);
    this.reference.scale.setScalar(0.77);
    if (changed) this.resetView();
  }

  setAutoRotate(enabled: boolean): void {
    this.controls.autoRotate = enabled;
  }

  setLighting(preset: "studio" | "soft" | "dramatic"): void {
    const values =
      preset === "soft"
        ? [2.0, 1.8, 1.3, 2.8]
        : preset === "dramatic"
          ? [3.8, 0.35, 4.2, 0.65]
          : [3.2, 1.5, 3.3, 1.9];
    [
      this.key.intensity,
      this.fill.intensity,
      this.rim.intensity,
      this.ambient.intensity,
    ] = values;
  }

  setView(view: "front" | "side" | "three-quarter"): void {
    const distance =
      (this.compare ? 6.5 : 4.9) * Math.max(1, 1 / this.camera.aspect);
    this.controls.target.set(0, -0.05, 0);
    if (view === "side") this.camera.position.set(distance, 0.03, 0);
    else if (view === "three-quarter")
      this.camera.position.set(distance * 0.58, 0.19, distance * 0.82);
    else this.camera.position.set(0, 0.03, distance);
    this.controls.update();
  }

  resetView(): void {
    this.setView("front");
  }
  setBackground(showGrid: boolean): void {
    this.grid.visible = showGrid;
  }

  /** Translation is retained as metadata; camera-space units need backend calibration. */
  setPose(pose: { R: number[]; t: number[] }): void {
    if (
      pose.R.length !== 9 ||
      pose.t.length !== 3 ||
      [...pose.R, ...pose.t].some((value) => !Number.isFinite(value))
    )
      throw new Error("姿态数据格式无效。");
    if (!this.model) return;
    const r = pose.R;
    const rotation = new THREE.Matrix4().set(
      r[0],
      r[1],
      r[2],
      0,
      r[3],
      r[4],
      r[5],
      0,
      r[6],
      r[7],
      r[8],
      0,
      0,
      0,
      0,
      1,
    );
    this.model.quaternion.setFromRotationMatrix(rotation).normalize();
    this.reference?.quaternion.copy(this.model.quaternion);
    this.model.userData.poseTranslation = [...pose.t];
  }

  loadDemo(): void {
    this.modelRequest?.abort();
    this.textureRequest?.abort();
    this.loadVersion++;
    this.textureVersion++;
    this.assetMode = "age_morph";
    this.referenceAge = 30;
    this.age = 30;
    const root = new THREE.Group();
    root.name = "AgeMorph3D_Demo";
    root.userData = {
      synthetic: true,
      source: "procedural-demo",
      trainedPrediction: false,
    };
    root.add(createDemoHead());
    this.replaceModel(root);
    this.resetView();
  }

  async loadModel(url: string, options: ModelOptions): Promise<void> {
    if (options.asset_mode !== "static" && options.asset_mode !== "age_morph")
      throw new Error("必须明确指定静态或年龄形变资产模式。");
    if (options.asset_mode === "age_morph" && options.source_age.value === null)
      throw new Error("年龄形变资产必须有已知源年龄。");
    this.clearResearchDisplay();
    const version = ++this.loadVersion;
    this.modelRequest?.abort();
    const controller = new AbortController();
    this.modelRequest = controller;
    const bytes = await localAsset(url, 64 * 1024 * 1024, controller.signal);
    if (this.disposed || version !== this.loadVersion) return;
    const manager = new THREE.LoadingManager();
    // V1 accepts self-contained GLB assets; remote sidecars are never requested.
    manager.setURLModifier((resource) => {
      if (
        resource === url ||
        resource.startsWith("blob:") ||
        resource.startsWith("data:")
      )
        return resource;
      throw new Error("模型包含外部资源。请导出带内嵌材质的独立 GLB 文件。");
    });
    const gltf = await new GLTFLoader(manager).parseAsync(bytes, "");
    const asset = gltf.scene;
    try {
      if (this.disposed || version !== this.loadVersion) {
        disposeObject(asset);
        return;
      }
      let meshCount = 0;
      let morphCount = 0;
      let vertices = 0;
      let synthetic = false;
      asset.traverse((node) => {
        if (node.userData.synthetic === true) synthetic = true;
        if (!(node instanceof THREE.Mesh)) return;
        if (node instanceof THREE.SkinnedMesh)
          throw new Error(
            "当前查看器需要静态网格的年龄形变模型，暂不支持骨骼蒙皮。",
          );
        meshCount++;
        const positions = node.geometry.getAttribute("position");
        if (!positions || positions.count < 3)
          throw new Error("模型网格为空或缺少顶点。");
        vertices += positions.count;
        if (vertices > 1_500_000)
          throw new Error("模型超过 150 万顶点，请先简化网格。");
        for (let index = 0; index < positions.array.length; index++)
          if (!Number.isFinite(positions.array[index]))
            throw new Error("模型包含无效顶点坐标。");
        if (options.capabilities?.age_texture) assertTextureUv(node);
        (Array.isArray(node.material) ? node.material : [node.material]).forEach((material) => {
          if ((material instanceof THREE.MeshStandardMaterial || material instanceof THREE.MeshBasicMaterial) && material.map)
            assertTextureUv(node, material.map.channel);
        });
        const targets = node.geometry.morphAttributes.position;
        if (options.asset_mode === "static" && Object.values(node.geometry.morphAttributes).some((attributes) => Array.isArray(attributes) && attributes.length > 0))
          throw new Error("静态重建资产不能包含形变目标，请检查资产模式。");
        if (options.asset_mode === "age_morph" && targets?.length) {
          if (
            !AGES.every(
              (age) => node.morphTargetDictionary?.[`age_${age}`] !== undefined,
            )
          )
            throw new Error(
              "年龄网格必须包含 age_20、age_45、age_70 三个命名形变目标。",
            );
          for (const age of AGES) {
            const target = targets[node.morphTargetDictionary![`age_${age}`]];
            if (!target || target.count !== positions.count)
              throw new Error("年龄形变目标与基础网格的顶点数量不一致。");
            for (let index = 0; index < target.array.length; index++)
              if (!Number.isFinite(target.array[index]))
                throw new Error("年龄形变目标包含无效坐标。");
          }
          morphCount++;
        }
      });
      if (!meshCount)
        throw new Error("未找到有效三维网格。");
      if (options.asset_mode === "age_morph" && !morphCount)
        throw new Error("未找到带 age_20 / age_45 / age_70 的有效年龄网格。");
      const bounds = new THREE.Box3().setFromObject(asset);
      const size = bounds.getSize(new THREE.Vector3());
      const maximum = Math.max(size.x, size.y, size.z);
      if (!Number.isFinite(maximum) || maximum < 0.000001)
        throw new Error("模型边界无效。");
      const normalization = new THREE.Group();
      normalization.name = "Asset_Normalization";
      normalization.scale.setScalar(2.8 / maximum);
      const center = bounds.getCenter(new THREE.Vector3());
      asset.position.sub(center);
      normalization.add(asset);
      const root = new THREE.Group();
      root.name = "AgeMorph3D_Loaded_Model";
      root.userData = {
        source: "loaded-glb",
        synthetic,
        asset_mode: options.asset_mode,
        source_age: { ...options.source_age },
        topology_id: options.topology_id,
        ...(options.asset_mode === "age_morph" ? { ageAnchors: [...AGES] } : {}),
      };
      root.add(normalization);
      this.textureVersion++;
      this.textureRequest?.abort();
      this.assetMode = options.asset_mode;
      this.referenceAge = options.source_age.value;
      if (options.source_age.value !== null) this.age = options.source_age.value;
      this.replaceModel(root);
      this.resetView();
    } catch (error) {
      disposeObject(asset);
      throw error;
    }
  }

  private disposeResearchTexture(): void {
    this.researchTexture?.dispose();
    this.researchTexture = null;
    if (this.researchCanvas) {
      this.researchCanvas.width = 0;
      this.researchCanvas.height = 0;
    }
    this.researchCanvas = null;
  }

  private clearResearchDisplay(): void {
    this.researchMaterialStates.forEach((state, material) => {
      Object.assign(material, state);
      material.needsUpdate = true;
    });
    this.researchMaterialStates.clear();
    this.disposeResearchTexture();
    if (this.model) {
      if (this.researchTextureAge?.present)
        this.model.userData.texture_age = this.researchTextureAge.value;
      else if (this.researchTextureAge) delete this.model.userData.texture_age;
      delete this.model.userData.research_display;
    }
    this.researchTextureAge = null;
  }

  /** Opt-in rendered research derivative; grants no age or texture capability. */
  setResearchDisplayTexture(frame: ResearchTextureFrame | null): void {
    if (frame === null) {
      this.textureVersion++;
      this.textureRequest?.abort();
      this.clearResearchDisplay();
      return;
    }
    if (this.disposed || !this.model || this.assetMode !== "static" || !this.bindings.length)
      throw new Error("研究显示需要已加载的静态网格。");
    if (
      !frame || frame.kind !== "research-display-only" ||
      !Number.isInteger(frame.width) || !Number.isInteger(frame.height) ||
      frame.width < 1 || frame.height < 1 || frame.width * frame.height > 16_000_000 ||
      !(frame.rgba instanceof Uint8ClampedArray) ||
      frame.rgba.length !== frame.width * frame.height * 4 ||
      !Number.isFinite(frame.targetAge) || frame.targetAge < 20 || frame.targetAge > 70 ||
      (frame.sourceLabel !== null && (!Number.isFinite(frame.sourceLabel) || frame.sourceLabel < 20 || frame.sourceLabel > 70)) ||
      typeof frame.exactSource !== "boolean" ||
      frame.exactSource !== (frame.sourceLabel !== null && frame.targetAge === frame.sourceLabel)
    ) throw new Error("研究纹理帧、年龄标签或像素尺寸无效。");
    const materials = new Set<ColorMaterial>();
    for (const binding of this.bindings) {
      assertTextureUv(binding.mesh);
      for (const material of Array.isArray(binding.material) ? binding.material : [binding.material]) {
        if (!(material instanceof THREE.MeshStandardMaterial) && !(material instanceof THREE.MeshBasicMaterial))
          throw new Error("当前网格材质不支持研究纹理显示。");
        materials.add(material);
      }
    }
    // Own a copy: a sampler may return its immutable original-source pixels.
    const pixels = new Uint8ClampedArray(frame.rgba);
    for (let index = 0; index < pixels.length; index += 4)
      if (pixels[index + 3] === 0 && (pixels[index] || pixels[index + 1] || pixels[index + 2]))
        throw new Error("研究纹理的未知区域必须保持透明黑色。");
    const canvas = document.createElement("canvas");
    canvas.width = frame.width;
    canvas.height = frame.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("浏览器无法创建研究纹理画布。");
    context.putImageData(new ImageData(pixels, frame.width, frame.height), 0, 0);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.flipY = false;
    texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
    texture.magFilter = texture.minFilter = THREE.LinearFilter;
    texture.generateMipmaps = false;
    this.textureVersion++;
    this.textureRequest?.abort();
    this.disposeResearchTexture();
    this.researchTexture = texture;
    this.researchCanvas = canvas;
    if (!this.researchTextureAge) this.researchTextureAge = {
      present: Object.prototype.hasOwnProperty.call(this.model.userData, "texture_age"),
      value: this.model.userData.texture_age,
    };
    delete this.model.userData.texture_age;
    materials.forEach((material) => {
      if (!this.researchMaterialStates.has(material)) this.researchMaterialStates.set(material, {
        map: material.map,
        transparent: material.transparent,
        alphaTest: material.alphaTest,
        depthWrite: material.depthWrite,
        premultipliedAlpha: material.premultipliedAlpha,
        opacity: material.opacity,
      });
      material.map = texture;
      material.transparent = true;
      material.alphaTest = 0;
      material.depthWrite = false;
      material.premultipliedAlpha = false;
      material.opacity = 1;
      material.needsUpdate = true;
    });
    this.model.userData.research_display = {
      kind: frame.kind,
      target_condition: frame.targetAge,
      source_research_label: frame.sourceLabel,
      exact_source: frame.exactSource,
      rendered_derivative: true,
    };
  }

  private restoreTexture(): void {
    this.clearResearchDisplay();
    this.originalMaps.forEach((map, material) => {
      material.map = map;
      material.needsUpdate = true;
    });
    this.uploadedTexture?.dispose();
    this.uploadedTexture = null;
  }

  async setTexture(url: string | null, asBase = false, targetAge?: number): Promise<void> {
    if (targetAge !== undefined) getAgeWeights(targetAge);
    this.clearResearchDisplay();
    const version = ++this.textureVersion;
    this.textureRequest?.abort();
    if (!url) {
      this.restoreTexture();
      if (this.model) delete this.model.userData.texture_age;
      return;
    }
    if (!this.bindings.length) throw new Error("当前没有可应用纹理的网格。");
    for (const binding of this.bindings) {
      assertTextureUv(binding.mesh);
      const materials = Array.isArray(binding.material) ? binding.material : [binding.material];
      if (materials.some((material) => !(material instanceof THREE.MeshStandardMaterial) && !(material instanceof THREE.MeshBasicMaterial)))
        throw new Error("当前网格材质不支持颜色纹理，请重新生成资产。");
    }
    const controller = new AbortController();
    this.textureRequest = controller;
    const bytes = await localAsset(url, 16 * 1024 * 1024, controller.signal);
    if (this.disposed || version !== this.textureVersion) return;
    const objectUrl = URL.createObjectURL(new Blob([bytes]));
    let texture: THREE.Texture;
    try {
      texture = await new THREE.TextureLoader().loadAsync(objectUrl);
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
    if (this.disposed || version !== this.textureVersion) {
      texture.dispose();
      return;
    }
    const image = texture.image as HTMLImageElement;
    if (image.width * image.height > 16_000_000) {
      texture.dispose();
      throw new Error("纹理超过 1600 万像素，请在后端缩小后重试。");
    }
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.flipY = false;
    texture.anisotropy = Math.min(
      8,
      this.renderer.capabilities.getMaxAnisotropy(),
    );
    this.restoreTexture();
    if (asBase) {
      if (this.model) delete this.model.userData.texture_age;
      this.originalTextures.add(texture);
      this.originalMaps.forEach((_map, material) => {
        this.originalMaps.set(material, texture);
        material.map = texture;
        material.needsUpdate = true;
      });
      return;
    }
    this.uploadedTexture = texture;
    if (this.model) {
      if (targetAge === undefined) delete this.model.userData.texture_age;
      else this.model.userData.texture_age = targetAge;
    }
    const materials = new Set(
      this.bindings.flatMap((binding) =>
        Array.isArray(binding.material) ? binding.material : [binding.material],
      ),
    );
    materials.forEach((material) => {
      if (
        material instanceof THREE.MeshStandardMaterial ||
        material instanceof THREE.MeshBasicMaterial
      ) {
        material.map = texture;
        material.needsUpdate = true;
      }
    });
  }

  async exportGLB(): Promise<Blob> {
    if (!this.model || this.disposed) throw new Error("没有可导出的三维模型。");
    const snapshot = this.model.clone(true);
    snapshot.position.set(0, 0, 0);
    snapshot.scale.setScalar(1);
    snapshot.visible = true;
    const snapshotMeshes: THREE.Mesh[] = [];
    const helpers: THREE.Object3D[] = [];
    snapshot.traverse((node) => {
      if (node.userData.agemorphDisplayHelper) helpers.push(node);
      if (node instanceof THREE.Mesh) snapshotMeshes.push(node);
    });
    helpers.forEach((helper) => helper.removeFromParent());
    const materials = new Map<THREE.Material, THREE.Material>();
    const textures = new Map<THREE.Texture, THREE.Texture>();
    const cloneMaterial = (source: THREE.Material): THREE.Material => {
      const existing = materials.get(source);
      if (existing) return existing;
      const clone = source.clone();
      materials.set(source, clone);
      // Freeze CPU image pixels before yielding: changing the input may close the original ImageBitmap.
      for (const [key, value] of Object.entries(source)) {
        if (!(value instanceof THREE.Texture)) continue;
        if (!textures.has(value)) {
          const image = value.image as CanvasImageSource & {
            width: number;
            height: number;
          };
          const canvas = document.createElement("canvas");
          canvas.width = image.width;
          canvas.height = image.height;
          const context = canvas.getContext("2d");
          if (!context) throw new Error("浏览器无法复制导出纹理。");
          context.drawImage(image, 0, 0);
          const texture = value.clone();
          texture.source = new THREE.Source(canvas);
          texture.needsUpdate = true;
          textures.set(value, texture);
        }
        (clone as unknown as Record<string, unknown>)[key] =
          textures.get(value);
      }
      return clone;
    };
    const cleanup = (): void => {
      materials.forEach((material) => material.dispose());
      textures.forEach((texture) => texture.dispose());
    };
    try {
      snapshotMeshes.forEach((mesh, index) => {
        const material = this.bindings[index].material;
        mesh.material = Array.isArray(material)
          ? material.map(cloneMaterial)
          : cloneMaterial(material);
      });
      snapshot.userData = {
        ...snapshot.userData,
        generator: "AgeMorph3D frontend",
        ...(this.assetMode === "age_morph"
          ? { age: this.age, ageAnchors: [...AGES] }
          : {}),
        generatedAt: new Date().toISOString(),
      };
      const { GLTFExporter } =
        await import("three/addons/exporters/GLTFExporter.js");
      const output = await new GLTFExporter().parseAsync(snapshot, {
        binary: true,
        onlyVisible: false,
      });
      if (!(output instanceof ArrayBuffer))
        throw new Error("GLB 导出没有返回二进制数据。");
      return new Blob([output], { type: "model/gltf-binary" });
    } finally {
      cleanup();
    }
  }

  async exportPNG(): Promise<Blob> {
    if (this.disposed || this.lostContext)
      throw new Error("当前 WebGL 画布不可导出。");
    this.renderer.render(this.scene, this.camera);
    return new Promise((resolve, reject) => {
      this.renderer.domElement.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("截图生成失败。"))),
        "image/png",
      );
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.modelRequest?.abort();
    this.textureRequest?.abort();
    this.loadVersion++;
    this.textureVersion++;
    cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.releaseModel();
    this.wireMaterial.dispose();
    this.invisibleMaterial.dispose();
    this.pointMaterial.dispose();
    disposeObject(this.grid);
    this.renderer.domElement.removeEventListener(
      "webglcontextlost",
      this.onContextLost,
    );
    this.renderer.domElement.removeEventListener(
      "webglcontextrestored",
      this.onContextRestored,
    );
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}
