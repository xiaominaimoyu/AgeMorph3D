"""Convert hash-verified 3DDFA_V2 NumPy assets into the probe's safe NPZ format.

This is a constrained legacy-asset converter, not a general pickle reader. A
caller-provided hash verifies integrity, not provenance or permission: acquire
and authorize the upstream assets before invoking this tool. No downloads,
checkpoint conversion, torch execution, or license acceptance occur here.

Source layout: https://github.com/cleardusk/3DDFA_V2/blob/master/bfm/bfm.py
The upstream noneck model uses separate configs/tri.pkl, transposed from 3 x M;
its keypoints address flattened xyz coordinates, not vertices directly.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import pickle
import re
import tempfile
from pathlib import Path

import numpy as np
from numpy._core import multiarray

CONVERSION_VERSION = "agemorph3d-3ddfa-npz-v2"
_MAX_SOURCE_BYTES = 512 * 1024**2
_MAX_ARRAY_BYTES = 512 * 1024**2
_MAX_VERTICES = 1_500_000


def _legacy_bytes(value: str, encoding: str = "latin1", errors: str = "strict") -> bytes:
    """Permit the exact legacy NumPy byte encoding without resolving any codec."""
    if (
        not isinstance(value, str)
        or encoding not in {"latin1", "latin-1", "iso-8859-1"}
        or errors != "strict"
        or len(value) > _MAX_SOURCE_BYTES
    ):
        raise pickle.UnpicklingError("Unsupported legacy NumPy byte encoding.")
    return value.encode("latin1", "strict")


class _NumpyAssetUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if module == "numpy" and name in {"ndarray", "dtype"}:
            return {"ndarray": np.ndarray, "dtype": np.dtype}[name]
        if module in {"numpy.core.multiarray", "numpy._core.multiarray"}:
            if name == "_reconstruct":
                return multiarray._reconstruct
            if name == "scalar":
                return multiarray.scalar
        if module == "_codecs" and name == "encode":
            return _legacy_bytes
        raise pickle.UnpicklingError("Pickle global is outside the NumPy asset allowlist.")

    def persistent_load(self, pid):
        raise pickle.UnpicklingError("Persistent pickle references are forbidden.")


def _read_verified(path: Path, expected_sha256: str) -> bytes:
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", expected_sha256
    ):
        raise ValueError("Each source requires an explicit 64-character SHA-256.")
    if not 0 < path.stat().st_size <= _MAX_SOURCE_BYTES:
        raise ValueError("Source asset is empty or exceeds the 512 MiB conversion budget.")
    data = path.read_bytes()
    if len(data) > _MAX_SOURCE_BYTES or hashlib.sha256(data).hexdigest() != expected_sha256.lower():
        raise ValueError("Source asset SHA-256 does not match; no pickle loading was attempted.")
    return data


def _load_numpy_asset(data: bytes) -> object:
    stream = io.BytesIO(data)
    result = _NumpyAssetUnpickler(stream, encoding="latin1").load()
    if stream.read(1):
        raise pickle.UnpicklingError("Trailing data after the NumPy asset is forbidden.")
    pending = [(result, 0)]
    arrays_bytes, nodes = 0, 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > 20 or nodes > 10_000:
            raise ValueError("NumPy asset container exceeds the structural budget.")
        if isinstance(value, np.ndarray):
            if value.dtype.kind not in "biuf":
                raise ValueError("Object, structured and non-real arrays are forbidden.")
            arrays_bytes += value.nbytes
            if arrays_bytes > _MAX_ARRAY_BYTES:
                raise ValueError("NumPy asset exceeds the numeric array budget.")
        elif type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError("NumPy asset dictionaries require string keys.")
            pending.extend((item, depth + 1) for item in value.values())
        elif type(value) in {list, tuple}:
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, np.generic):
            if value.dtype.kind not in "biuf":
                raise ValueError("Non-numeric NumPy scalars are forbidden.")
        elif type(value) not in {type(None), bool, int, float, str, bytes, bytearray}:
            raise ValueError("Unexpected object in NumPy asset.")
    return result


def load_verified_numpy_pickle(path: str | Path, sha256: str) -> object:
    """Read only hash-matching NumPy assets using the fixed global allowlist."""
    return _load_numpy_asset(_read_verified(Path(path), sha256))


def _real_array(value: object, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real values.")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.array(array, dtype=np.float32, order="C", copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} cannot be represented in float32.")
    return result


def _convert_bfm(bfm: object, source_triangles: object) -> dict[str, np.ndarray]:
    if type(bfm) is not dict or not {"u", "w_shp", "w_exp", "keypoints"}.issubset(bfm):
        raise ValueError("BFM source is missing its required numeric arrays.")
    mean = _real_array(bfm["u"], "u")
    if mean.ndim == 1:
        mean = mean[:, None]
    if (
        mean.ndim != 2
        or mean.shape[1] != 1
        or mean.shape[0] % 3
        or not 3 <= mean.shape[0] // 3 <= _MAX_VERTICES
    ):
        raise ValueError("BFM u must encode a bounded (3N, 1) coordinate vector.")
    vertex_count = mean.shape[0] // 3
    bases = {}
    for name, dimensions in (("w_shp", 40), ("w_exp", 10)):
        basis = _real_array(bfm[name], name)
        if basis.ndim != 2 or basis.shape[0] != mean.shape[0] or basis.shape[1] < dimensions:
            raise ValueError(f"BFM {name} has incompatible coordinate/coefficient dimensions.")
        bases[name] = np.ascontiguousarray(basis[:, :dimensions])

    coordinate_indices = np.asarray(bfm["keypoints"])
    if coordinate_indices.shape != (204,) or coordinate_indices.dtype.kind not in "iu":
        raise ValueError("BFM keypoints must be exactly 204 integer coordinate indices.")
    if np.any(coordinate_indices < 0) or np.any(coordinate_indices >= mean.shape[0]):
        raise ValueError("BFM keypoint coordinate indices are outside u.")
    # Native sparse points can mix xyz coordinates from different vertices.
    # Preserve that upstream mapping exactly, without guessing a vertex or repair.
    keypoints = coordinate_indices.astype(np.int64)

    source_triangles = np.asarray(source_triangles)
    if (
        source_triangles.ndim != 2
        or source_triangles.shape[0] != 3
        or not source_triangles.shape[1]
        or source_triangles.dtype.kind not in "iu"
    ):
        raise ValueError("Explicit upstream tri.pkl must contain integer faces with shape (3, M).")
    if np.min(source_triangles) != 0 or np.max(source_triangles) >= vertex_count:
        raise ValueError("tri.pkl must demonstrate zero-based indexing; no index-base guessing.")
    triangles = np.array(source_triangles.T, dtype=np.int64, order="C", copy=True)
    if np.any(np.diff(np.sort(triangles, axis=1), axis=1) == 0):
        raise ValueError("Triangle faces must contain three distinct vertices.")
    return {"u": mean, **bases, "tri": triangles, "keypoints": keypoints}


def _convert_stats(stats: object) -> dict[str, np.ndarray]:
    if type(stats) is not dict or not {"mean", "std"}.issubset(stats):
        raise ValueError("Parameter statistics require mean and std arrays.")
    result = {}
    for name in ("mean", "std"):
        array = _real_array(stats[name], name)
        if array.shape not in {(62,), (62, 1), (1, 62)}:
            raise ValueError("Parameter statistics must encode exactly 62 values.")
        result[name] = array.reshape(62)
    if np.any(result["std"] <= 0):
        raise ValueError("Parameter standard deviations must be strictly positive.")
    return result


def prepare_tddfa(
    *,
    bfm: str | Path,
    bfm_sha256: str,
    tri: str | Path,
    tri_sha256: str,
    stats: str | Path,
    stats_sha256: str,
    output_dir: str | Path,
) -> dict:
    """Validate all three sources before unpickling or publishing any output."""
    sources = {
        "bfm": (Path(bfm), bfm_sha256),
        "tri": (Path(tri), tri_sha256),
        "stats": (Path(stats), stats_sha256),
    }
    buffers = {role: _read_verified(path, sha) for role, (path, sha) in sources.items()}
    sources = {role: (path, sha.lower()) for role, (path, sha) in sources.items()}
    model = _convert_bfm(_load_numpy_asset(buffers["bfm"]), _load_numpy_asset(buffers["tri"]))
    parameters = _convert_stats(_load_numpy_asset(buffers["stats"]))
    output_root = Path(output_dir)
    names = ("bfm.npz", "param_stats.npz", "conversion.json")
    if any((output_root / name).exists() for name in names):
        raise FileExistsError("Conversion outputs already exist; refusing to overwrite them.")
    output_root.mkdir(parents=True, exist_ok=True)

    groups = model["keypoints"].reshape(68, 3)
    noncontiguous = np.flatnonzero(
        (groups[:, 0] % 3 != 0)
        | np.any(groups != groups[:, :1] + np.array([0, 1, 2], dtype=np.int64), axis=1)
    )
    report = {
        "conversion_version": CONVERSION_VERSION,
        "coordinate_system": "bfm_model_raw",
        "sources": {
            role: {"name": path.name, "sha256": sha, "size_bytes": len(buffers[role])}
            for role, (path, sha) in sources.items()
        },
        "vertex_count": model["u"].shape[0] // 3,
        "triangle_count": model["tri"].shape[0],
        "shape_dimensions": 40,
        "expression_dimensions": 10,
        "keypoints_conversion": "preserved 204 native flattened coordinate indices; no repairs",
        "keypoints_semantics": "native_sparse_points_not_vertex_mapping",
        "noncontiguous_groups": [
            {"index": int(index), "coordinate_indices": groups[index].tolist()}
            for index in noncontiguous
        ],
        "triangles_conversion": "explicit tri.pkl (3,M), zero-based, transposed to (M,3)",
        "license_note": "Conversion does not grant permission or declare service readiness.",
    }
    published = []
    with tempfile.TemporaryDirectory(prefix=".prepare-tddfa-", dir=output_root) as temporary:
        staging = Path(temporary)
        np.savez_compressed(
            staging / "bfm.npz",
            **model,
            conversion_version=np.array(CONVERSION_VERSION),
            source_bfm_sha256=np.array(sources["bfm"][1]),
            source_tri_sha256=np.array(sources["tri"][1]),
        )
        np.savez_compressed(
            staging / "param_stats.npz",
            **parameters,
            conversion_version=np.array(CONVERSION_VERSION),
            source_stats_sha256=np.array(sources["stats"][1]),
        )
        report["outputs"] = {
            name: {
                "sha256": hashlib.sha256((staging / name).read_bytes()).hexdigest(),
                "size_bytes": (staging / name).stat().st_size,
            }
            for name in names[:2]
        }
        (staging / "conversion.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        try:
            # Hard links publish complete files and atomically refuse existing targets.
            for name in names:
                target = output_root / name
                os.link(staging / name, target)
                published.append(target)
        except OSError:
            for target in published:
                target.unlink()
            raise
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ("bfm", "tri", "stats"):
        parser.add_argument(f"--{role}", required=True, type=Path)
        parser.add_argument(f"--{role}-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = vars(parser.parse_args(argv))
    try:
        report = prepare_tddfa(**args)
    except (ValueError, OSError, pickle.UnpicklingError, EOFError) as error:
        parser.exit(2, f"prepare_tddfa: {error}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
