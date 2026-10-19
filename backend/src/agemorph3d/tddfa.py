"""B0-only 3DDFA_V2 CPU probe; raw BFM coordinates are not canonical geometry.

Numerical conventions are checked against the upstream implementations:
https://github.com/cleardusk/3DDFA_V2/blob/master/TDDFA_ONNX.py
https://github.com/cleardusk/3DDFA_V2/blob/master/utils/functions.py
https://github.com/cleardusk/3DDFA_V2/blob/master/utils/tddfa_util.py

Only a separately verified ONNX regressor and safe NPZ assets are accepted. This
module never downloads, converts checkpoints, accepts licenses, or loads pickle.
The projection includes scale/shear; it must not be reported as a pure rotation.
Synthetic tests establish numerical behavior, not real-model B0 acceptance.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
import onnxruntime as ort
from numpy.typing import NDArray

if TYPE_CHECKING:
    from .model_assets import VerifiedModelAssets

_IMAGE_SIZE = 120
_MAX_IMAGE_PIXELS = 16_000_000
_MAX_CROP_PIXELS = 64_000_000
_MAX_VERTICES = 1_500_000
_MAX_ONNX_BYTES = 128 * 1024**2
_MAX_NPZ_BYTES = 512 * 1024**2


@dataclass(frozen=True)
class TddfaResult:
    """Identity/expression geometry before applying the regressed projection.

    ``roi`` is the floating-point source-image rectangle (left, top, right,
    bottom). The crop uses rounded boundaries and zero padding as upstream does.
    ``projection`` maps raw vertices into the regressor crop space; image-space
    projection additionally needs upstream's axis/ROI transformation. No pose,
    metric unit, canonical orientation, or UV correspondence is inferred here.
    """

    shape: NDArray[np.float32]
    expr: NDArray[np.float32]
    vertices: NDArray[np.float32]
    triangles: NDArray[np.int64]
    projection: NDArray[np.float32]
    roi: tuple[float, float, float, float]
    topology_sha256: str
    coordinate_system: str = "bfm_model_raw"


def project_vertices(
    result: TddfaResult, coordinate_indices: NDArray[np.int64] | None = None
) -> NDArray[np.float32]:
    """Apply the upstream 120px crop projection and ROI map to original pixels.

    This is an affine image projection for B0 overlay checks, not a metric camera
    or a canonical-to-viewer rotation. Depth is upstream's shifted relative depth.
    """
    vertices = result.vertices
    if coordinate_indices is not None:
        # Upstream sparse landmarks address individual XYZ coordinates. One native
        # triplet is noncontiguous; preserve it instead of silently changing depth.
        coordinates = _indices(coordinate_indices, "keypoint coordinates", vertices.size)
        if coordinates.shape != (68, 3):
            raise ValueError("Sparse keypoint coordinates must have shape (68,3).")
        vertices = vertices.reshape(-1)[coordinates]
    projected = result.projection[:, :3] @ vertices.T + result.projection[:, 3:4]
    projected[0] -= 1
    projected[2] -= 1
    projected[1] = _IMAGE_SIZE - projected[1]
    left, top, right, bottom = result.roi
    scale_x, scale_y = (right - left) / _IMAGE_SIZE, (bottom - top) / _IMAGE_SIZE
    projected[0] = projected[0] * scale_x + left
    projected[1] = projected[1] * scale_y + top
    projected[2] *= (scale_x + scale_y) / 2
    projected[2] -= projected[2].min()
    if not np.isfinite(projected).all():
        raise ValueError("Projected vertices must be finite.")
    return np.ascontiguousarray(projected.T)


def _finite_array(value: object, name: str) -> NDArray[np.float32]:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real numbers.")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.array(array, dtype=np.float32, order="C", copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} is outside the float32 range.")
    return result


def _indices(value: object, name: str, vertex_count: int) -> NDArray[np.int64]:
    array = np.asarray(value)
    if array.dtype.kind not in "iu" or not array.size:
        raise ValueError(f"{name} must contain integer vertex indices.")
    if np.any(array < 0) or np.any(array >= vertex_count):
        raise ValueError(f"{name} indices must be zero-based and within the mesh.")
    result = np.array(array, dtype=np.int64, order="C", copy=True)
    result.setflags(write=False)
    return result


def _npz_arrays(path: Path, names: tuple[str, ...]) -> dict[str, NDArray]:
    if path.suffix.lower() != ".npz":
        raise ValueError("BFM and parameter statistics must use safe NPZ files.")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if (
                len({entry.filename for entry in entries}) != len(entries)
                or any(entry.file_size > _MAX_NPZ_BYTES for entry in entries)
                or sum(entry.file_size for entry in entries) > _MAX_NPZ_BYTES
            ):
                raise ValueError("NPZ archive is ambiguous or exceeds the 512 MiB unpacked budget.")
    except zipfile.BadZipFile as error:
        raise ValueError("NPZ asset must be a valid ZIP archive.") from error
    # Object arrays fail on access with allow_pickle=False; no fallback is allowed.
    with np.load(path, allow_pickle=False) as archive:
        if not set(names).issubset(archive.files):
            raise ValueError("NPZ asset is missing required arrays.")
        return {name: archive[name] for name in names}


def _prepare_input(
    rgb: NDArray[np.uint8], bbox: object
) -> tuple[NDArray[np.float32], tuple[float, float, float, float]]:
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 1
        or rgb.shape[0] * rgb.shape[1] > _MAX_IMAGE_PIXELS
    ):
        raise ValueError("rgb must be a nonempty uint8 H x W x 3 image within 16 MP.")
    box = _finite_array(bbox, "bbox")
    if box.shape != (4,) or box[2] <= 0 or box[3] <= 0:
        raise ValueError("bbox must be x, y, positive width, positive height.")
    x, y, width, height = (float(item) for item in box)
    image_height, image_width = rgb.shape[:2]
    if x >= image_width or y >= image_height or x + width <= 0 or y + height <= 0:
        raise ValueError("bbox must intersect the source image.")

    average_side = (width + height) / 2
    crop_side = int(average_side * 1.58)
    center_x = x + width / 2
    center_y = y + height / 2 + average_side * 0.14
    roi = (
        center_x - crop_side / 2,
        center_y - crop_side / 2,
        center_x + crop_side / 2,
        center_y + crop_side / 2,
    )
    left, top, right, bottom = (round(value) for value in roi)
    crop_width, crop_height = right - left, bottom - top
    if min(crop_width, crop_height) < 1 or crop_width * crop_height > _MAX_CROP_PIXELS:
        raise ValueError("Expanded bbox crop is empty or exceeds the bounded crop budget.")

    # Copy only the intersection into a black canvas, then convert RGB to BGR.
    crop = np.zeros((crop_height, crop_width, 3), dtype=np.uint8)
    source_left, source_top = max(0, left), max(0, top)
    source_right, source_bottom = min(image_width, right), min(image_height, bottom)
    if source_right > source_left and source_bottom > source_top:
        crop[
            source_top - top : source_bottom - top,
            source_left - left : source_right - left,
        ] = rgb[source_top:source_bottom, source_left:source_right]
    resized = cv2.resize(
        crop[..., ::-1], (_IMAGE_SIZE, _IMAGE_SIZE), interpolation=cv2.INTER_LINEAR
    )
    tensor = resized.transpose(2, 0, 1)[None].astype(np.float32)
    tensor -= np.float32(127.5)
    tensor /= np.float32(128)
    return np.ascontiguousarray(tensor), roi


class TddfaOnnx:
    """A fixed 62-parameter CPU regressor backed by manifest-verified assets.

    ``license_verified`` is retained from the asset verifier. A research probe
    using unresolved assets never becomes production-ready through this class.
    ``topology_sha256`` hashes the vertex count, ordered faces and ordered 204
    coordinate indices with versioned little-endian encoding; basis hashes remain in the
    asset manifest. Input images must already have EXIF orientation applied.
    """

    provider = "CPUExecutionProvider"

    def __init__(self, assets: VerifiedModelAssets) -> None:
        if assets.manifest.backend != "3ddfa_v2_onnx" or set(assets.paths) != {
            "regressor",
            "bfm",
            "param_stats",
        }:
            raise ValueError("3DDFA requires exactly regressor, bfm and param_stats artifacts.")
        self.license_verified = assets.license_verified
        regressor_path = Path(assets.paths["regressor"])
        bfm_path = Path(assets.paths["bfm"])
        stats_path = Path(assets.paths["param_stats"])
        if regressor_path.stat().st_size > _MAX_ONNX_BYTES:
            raise ValueError("B0 regressor exceeds the 128 MiB in-memory model budget.")

        bfm = _npz_arrays(bfm_path, ("u", "w_shp", "w_exp", "tri", "keypoints"))
        self._u = _finite_array(bfm["u"], "u")
        if (
            self._u.ndim != 2
            or self._u.shape[1] != 1
            or self._u.shape[0] % 3
            or not 3 <= self._u.shape[0] // 3 <= _MAX_VERTICES
        ):
            raise ValueError("u must have shape (3N, 1) for a bounded nonempty mesh.")
        vertex_count = self._u.shape[0] // 3
        self._shape_basis = _finite_array(bfm["w_shp"], "w_shp")
        self._expr_basis = _finite_array(bfm["w_exp"], "w_exp")
        for name, basis, dimensions in (
            ("w_shp", self._shape_basis, 40),
            ("w_exp", self._expr_basis, 10),
        ):
            if basis.ndim != 2 or basis.shape[0] != 3 * vertex_count or basis.shape[1] < dimensions:
                raise ValueError(f"{name} has incompatible vertex/coefficient dimensions.")
        self._shape_basis = self._shape_basis[:, :40]
        self._expr_basis = self._expr_basis[:, :10]
        self.triangles = _indices(bfm["tri"], "tri", vertex_count)
        if self.triangles.ndim != 2 or self.triangles.shape[1] != 3:
            raise ValueError("tri must have shape (M, 3).")
        if np.any(np.diff(np.sort(self.triangles, axis=1), axis=1) == 0):
            raise ValueError("Triangle faces must contain three distinct vertex indices.")
        coordinates = _indices(bfm["keypoints"], "keypoint coordinates", 3 * vertex_count)
        if coordinates.shape != (204,):
            raise ValueError("keypoints must preserve 204 individual coordinate indices.")
        self.keypoint_coordinates = coordinates.reshape(68, 3)

        digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
        for array in (
            np.array([vertex_count, len(self.triangles)], dtype="<i8"),
            self.triangles.astype("<i8"),
            self.keypoint_coordinates.astype("<i8"),
        ):
            digest.update(array.tobytes(order="C"))
        self.topology_sha256 = digest.hexdigest()

        stats = _npz_arrays(stats_path, ("mean", "std"))
        self._mean = _finite_array(stats["mean"], "mean")
        self._std = _finite_array(stats["std"], "std")
        if self._mean.shape != (62,) or self._std.shape != (62,) or np.any(self._std <= 0):
            raise ValueError("Parameter mean/std must have shape (62,) and std must be positive.")

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        # Bytes prevent ONNX Runtime from reading unregistered external-data files.
        self._session = ort.InferenceSession(
            regressor_path.read_bytes(), sess_options=options, providers=[self.provider]
        )
        if self._session.get_providers() != [self.provider]:
            raise ValueError("3DDFA B0 probe requires an actual CPU-only inference session.")
        inputs, outputs = self._session.get_inputs(), self._session.get_outputs()
        if (
            len(inputs) != 1
            or inputs[0].type != "tensor(float)"
            or inputs[0].shape != [1, 3, _IMAGE_SIZE, _IMAGE_SIZE]
            or len(outputs) != 1
            or outputs[0].type != "tensor(float)"
            or outputs[0].shape != [1, 62]
        ):
            raise ValueError("Regressor contract must be float32 [1,3,120,120] -> [1,62].")
        self._input_name, self._output_name = inputs[0].name, outputs[0].name

    def reconstruct(self, rgb: NDArray[np.uint8], bbox: object) -> TddfaResult:
        tensor, roi = _prepare_input(rgb, bbox)
        predictions = self._session.run([self._output_name], {self._input_name: tensor})
        if len(predictions) != 1:
            raise ValueError("Regressor returned an unexpected number of outputs.")
        prediction = _finite_array(predictions[0], "regressor output")
        if prediction.shape != (1, 62):
            raise ValueError("Regressor output must have shape (1, 62).")
        with np.errstate(over="raise", invalid="raise"):
            try:
                parameters = prediction[0] * self._std + self._mean
                shape, expr = parameters[12:52].copy(), parameters[52:62].copy()
                coordinates = self._u + self._shape_basis @ shape[:, None]
                coordinates += self._expr_basis @ expr[:, None]
            except FloatingPointError as error:
                raise ValueError(
                    "Regressor parameters or reconstructed vertices overflowed."
                ) from error
        # Parameter projection is row-major; BFM xyz triplets are Fortran-reshaped.
        projection = parameters[:12].reshape(3, 4).copy()
        vertices = coordinates.reshape(3, -1, order="F").T.copy()
        if not np.isfinite(vertices).all() or not np.isfinite(parameters).all():
            raise ValueError("Reconstruction must contain only finite values.")
        return TddfaResult(
            shape=shape,
            expr=expr,
            vertices=vertices,
            triangles=self.triangles,
            projection=projection,
            roi=roi,
            topology_sha256=self.topology_sha256,
        )
