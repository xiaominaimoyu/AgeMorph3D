/** API 1.2. Coefficient dimensions remain model-dependent until backend freeze. */
export interface Pose {
  /** Row-major 3 × 3 rotation matrix. */
  R: number[];
  t: number[];
}

export interface Capabilities {
  reconstruction: boolean;
  age_morph: boolean;
  age_texture: boolean;
  realtime: boolean;
}

export interface ModelStatus {
  /** unknown is a frontend fallback for legacy or malformed model status. */
  state: "missing" | "loading" | "ready" | "error" | "unknown";
  backend: string | null;
  provider: string | null;
  detail: string;
}

export interface Health {
  models: Record<string, ModelStatus>;
  device: string;
  version: string;
  api_version: string | null;
  /** null means unknown; it must never grant access to inference actions. */
  capabilities: Capabilities | null;
}

export interface SourceAge {
  value: number | null;
  method: "unknown" | "user" | "estimated";
  calibration_id: string | null;
}

export interface Reconstruction {
  mesh_id: string;
  topology_id: string;
  asset_mode: "static" | "age_morph";
  capabilities: Pick<Capabilities, "age_morph" | "age_texture">;
  source_age: SourceAge;
  shape: number[];
  expr: number[];
  pose: Pose;
  texture_url?: string;
}

export interface AgingResult {
  shape_aged: number[];
  texture_url?: string;
}

export interface FaceState {
  type: "face_state";
  seq: number;
  ts: number;
  /** Pixel coordinates in the submitted JPEG: x, y, width, height. */
  bbox: [number, number, number, number];
  landmarks: [number, number][];
  pose: Pose;
  conf: number;
  /** Sent only when coefficients change; omitted fields must not reset state. */
  shape?: number[];
  expr?: number[];
}

export interface FrameCallbacks {
  onState: (state: FaceState) => void;
  onStatus?: (text: string) => void;
  onError?: (message: string) => void;
}
