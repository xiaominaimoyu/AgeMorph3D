/** Draft API v1. Coefficient dimensions remain model-dependent until backend freeze. */
export interface Pose {
  /** Row-major 3 × 3 rotation matrix. */
  R: number[];
  t: number[];
}

export interface Health {
  models: Record<string, unknown>;
  device: string;
  version: string;
}

export interface Reconstruction {
  mesh_id: string;
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
