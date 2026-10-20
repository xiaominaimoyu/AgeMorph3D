import type { Pose } from "./contracts";

/** Dimensions of the actual, unmirrored JPEG submitted for this frame. */
export type FrameSize = readonly [width: number, height: number];

export function assertRotation(R: readonly number[]): void {
  if (R.length !== 9 || R.some((value) => !Number.isFinite(value)))
    throw new Error("姿态旋转矩阵格式无效。");
  for (let row = 0; row < 3; row++) {
    for (let other = row; other < 3; other++) {
      let dot = 0;
      for (let column = 0; column < 3; column++)
        dot += R[row * 3 + column]! * R[other * 3 + column]!;
      if (Math.abs(dot - (row === other ? 1 : 0)) > 0.001)
        throw new Error("姿态必须提供正交的纯旋转矩阵。");
    }
  }
  const determinant =
    R[0]! * (R[4]! * R[8]! - R[5]! * R[7]!) -
    R[1]! * (R[3]! * R[8]! - R[5]! * R[6]!) +
    R[2]! * (R[3]! * R[7]! - R[4]! * R[6]!);
  if (Math.abs(determinant - 1) > 0.001)
    throw new Error("姿态旋转不能包含镜面反射。");
}

/** Mirror the display rotation without reflecting mesh geometry: S R S. */
export function mirroredPose(pose: Pose): Pose {
  assertRotation(pose.R);
  const signs = [-1, 1, 1];
  return {
    R: pose.R.map((value, index) =>
      value * signs[Math.floor(index / 3)]! * signs[index % 3]!,
    ),
    t: [-pose.t[0]!, pose.t[1]!, pose.t[2]!],
  };
}
