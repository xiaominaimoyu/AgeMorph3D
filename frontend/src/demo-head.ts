import * as THREE from "three";

const gaussian = (
  x: number,
  y: number,
  cx: number,
  cy: number,
  sx: number,
  sy: number,
) => Math.exp(-((x - cx) ** 2 / (2 * sx * sx) + (y - cy) ** 2 / (2 * sy * sy)));

function smoothLongitudeSeam(
  normals: THREE.BufferAttribute,
  columns: number,
  rows: number,
): void {
  const normal = new THREE.Vector3();
  for (let row = 0; row <= rows; row++) {
    const first = row * (columns + 1);
    const last = first + columns;
    normal
      .set(
        normals.getX(first) + normals.getX(last),
        normals.getY(first) + normals.getY(last),
        normals.getZ(first) + normals.getZ(last),
      )
      .normalize();
    normals.setXYZ(first, normal.x, normal.y, normal.z);
    normals.setXYZ(last, normal.x, normal.y, normal.z);
  }
}

/** Original, synthetic geometry. It has no identity, biometric input, or trained prediction. */
function headPositions(
  age: number,
  columns: number,
  rows: number,
): Float32Array {
  const output = new Float32Array((columns + 1) * (rows + 1) * 3);
  const old = Math.max(0, (age - 45) / 25);
  const young = Math.max(0, (45 - age) / 25);
  for (let row = 0; row <= rows; row++) {
    const latitude = (Math.PI * row) / rows;
    const y0 = Math.cos(latitude);
    const ring = Math.sin(latitude);
    // The lower jaw narrows smoothly into a chin, while the cranium stays rounded.
    const jaw = 1 - 0.23 * Math.max(0, -y0) ** 1.2;
    for (let column = 0; column <= columns; column++) {
      const longitude = (2 * Math.PI * column) / columns;
      let x = Math.sin(longitude) * ring * 0.72 * jaw;
      let y = y0 * 1.02 + 0.24;
      let z = Math.cos(longitude) * ring * 0.67;
      const front = Math.max(0, Math.cos(longitude)) ** 8;
      const g = (cx: number, cy: number, sx: number, sy: number) =>
        gaussian(x, y, cx, cy, sx, sy);
      if (front > 0) {
        let shape = 0;
        shape += 0.16 * g(0, 0.36, 0.085, 0.26); // nasal bridge
        shape += 0.285 * g(0, 0.07, 0.095, 0.095); // nose tip
        shape +=
          0.085 * (g(-0.115, 0.035, 0.05, 0.04) + g(0.115, 0.035, 0.05, 0.04));
        shape -=
          0.045 *
          (g(-0.075, 0.001, 0.025, 0.018) + g(0.075, 0.001, 0.025, 0.018));
        shape -=
          0.13 * (g(-0.275, 0.37, 0.13, 0.082) + g(0.275, 0.37, 0.13, 0.082));
        shape +=
          0.062 * (g(-0.27, 0.5, 0.16, 0.055) + g(0.27, 0.5, 0.16, 0.055));
        shape +=
          (0.105 + 0.038 * young - 0.026 * old) *
          (g(-0.34, 0.07, 0.18, 0.15) + g(0.34, 0.07, 0.18, 0.15));
        shape += 0.052 * g(0, -0.22, 0.22, 0.065); // upper lip
        shape += 0.058 * g(0, -0.3, 0.21, 0.052); // lower lip
        shape -= 0.047 * g(0, -0.263, 0.23, 0.014); // mouth seam
        shape -= 0.024 * g(0, -0.1, 0.027, 0.05); // philtrum
        shape += 0.105 * g(0, -0.54, 0.23, 0.14); // chin
        shape -= 0.024 * g(0, -0.4, 0.2, 0.035);
        // Gentle structural changes and shallow creases make age interpolation visible.
        shape +=
          old *
          0.044 *
          (g(-0.4, -0.31, 0.12, 0.14) + g(0.4, -0.31, 0.12, 0.14));
        shape -=
          old *
          0.024 *
          (g(-0.28, 0.24, 0.15, 0.019) + g(0.28, 0.24, 0.15, 0.019));
        for (const crease of [0.68, 0.78, 0.88])
          shape -= old * 0.014 * g(0, crease, 0.39, 0.013);
        shape -=
          old *
          0.018 *
          (g(-0.22, -0.08, 0.024, 0.13) + g(0.22, -0.08, 0.024, 0.13));
        z += shape * front;
        y -=
          old *
          0.04 *
          (g(-0.37, -0.15, 0.18, 0.25) + g(0.37, -0.15, 0.18, 0.25)) *
          front;
        x *= 1 + 0.025 * young * g(0, 0, 0.55, 0.3);
      }
      const index = (row * (columns + 1) + column) * 3;
      output[index] = x;
      output[index + 1] = y;
      output[index + 2] = z;
    }
  }
  return output;
}

export function createDemoHead(): THREE.Group {
  const root = new THREE.Group();
  root.name = "AgeMorph3D_Synthetic_Demo";
  root.userData = {
    source: "procedural-demo",
    synthetic: true,
    trainedPrediction: false,
    description: "原创程序化示意模型；年龄形变不代表真实预测。",
  };
  const material = new THREE.MeshStandardMaterial({
    color: "#77b8bc",
    roughness: 0.56,
    metalness: 0.16,
  });
  const columns = 160;
  const rows = 120;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(headPositions(45, columns, rows), 3),
  );
  const uv: number[] = [];
  const indices: number[] = [];
  for (let row = 0; row <= rows; row++) {
    for (let column = 0; column <= columns; column++) {
      uv.push(column / columns, 1 - row / rows);
      if (row < rows && column < columns) {
        const a = row * (columns + 1) + column;
        const b = a + columns + 1;
        indices.push(a, b, a + 1, b, b + 1, a + 1);
      }
    }
  }
  geometry.setIndex(indices);
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  geometry.computeVertexNormals();
  smoothLongitudeSeam(
    geometry.getAttribute("normal") as THREE.BufferAttribute,
    columns,
    rows,
  );
  geometry.morphAttributes.position = [20, 45, 70].map((age) => {
    const attribute = new THREE.BufferAttribute(
      headPositions(age, columns, rows),
      3,
    );
    attribute.name = `age_${age}`;
    return attribute;
  });
  geometry.morphAttributes.normal = geometry.morphAttributes.position.map(
    (position) => {
      const temporary = new THREE.BufferGeometry();
      temporary.setAttribute("position", position);
      temporary.setIndex(geometry.index);
      temporary.computeVertexNormals();
      smoothLongitudeSeam(
        temporary.getAttribute("normal") as THREE.BufferAttribute,
        columns,
        rows,
      );
      const normals = temporary.getAttribute("normal").clone();
      temporary.dispose();
      return normals;
    },
  );
  geometry.morphTargetsRelative = false;
  const head = new THREE.Mesh(geometry, material);
  head.name = "Face_age_20_45_70";
  root.add(head);

  const ellipsoid = (
    name: string,
    position: [number, number, number],
    scale: [number, number, number],
    targetMaterial = material,
  ) => {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(1, 40, 28),
      targetMaterial,
    );
    mesh.name = name;
    mesh.position.set(...position);
    mesh.scale.set(...scale);
    root.add(mesh);
    return mesh;
  };
  ellipsoid("Ear_L", [-0.68, 0.12, -0.015], [0.105, 0.225, 0.15]);
  ellipsoid("Ear_R", [0.68, 0.12, -0.015], [0.105, 0.225, 0.15]);
  const neck = new THREE.Mesh(
    new THREE.CylinderGeometry(0.29, 0.43, 0.72, 56, 10),
    material,
  );
  neck.name = "Neck";
  neck.position.set(0, -0.94, -0.075);
  root.add(neck);
  const profile = [
    new THREE.Vector2(0, -1.54),
    new THREE.Vector2(0.83, -1.54),
    new THREE.Vector2(1.07, -1.45),
    new THREE.Vector2(1.05, -1.34),
    new THREE.Vector2(0.85, -1.2),
    new THREE.Vector2(0.52, -1.11),
    new THREE.Vector2(0.34, -1.03),
  ];
  const shoulders = new THREE.Mesh(
    new THREE.LatheGeometry(profile, 80),
    material,
  );
  shoulders.name = "Bust";
  shoulders.scale.z = 0.56;
  root.add(shoulders);
  const eyeMaterial = new THREE.MeshStandardMaterial({
    color: "#365e67",
    roughness: 0.58,
    metalness: 0.18,
  });
  ellipsoid("Eye_L", [-0.255, 0.37, 0.585], [0.105, 0.047, 0.036], eyeMaterial);
  ellipsoid("Eye_R", [0.255, 0.37, 0.585], [0.105, 0.047, 0.036], eyeMaterial);
  root.position.y = 0.12;
  return root;
}
