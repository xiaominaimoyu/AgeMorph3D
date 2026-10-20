"""Prepare a local, uncalibrated BFM age attribute direction without cross-basis guesses.

The authorized 2009 archive's apply_attributes.m uses the first 199 attribute
values and coef2object.m scales them by shapeEV/texEV. Its +/-50 examples name
Older/Younger, but do not establish a calendar-year calibration. SciPy is only
needed by this offline converter; inference never parses MAT, TAR or pickle.
No restricted model, derived data or license acceptance is distributed here.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
import zipfile
from pathlib import Path

import numpy as np

FORMAT = "agemorph3d-bfm-age-strength-v1"
_MAX_ARCHIVE_BYTES = 512 * 1024**2
_MAX_TAR_BYTES = 512 * 1024**2
_MAX_TARGET_BYTES = 64 * 1024**2
_MAX_VERTICES = 100_000
_MODEL_MEMBER = "PublicMM1/01_MorphableModel.mat"
_ATTR_MEMBER = "PublicMM1/04_attributes.mat"
_EXAMPLE_MEMBER = "PublicMM1/matlab/apply_attributes.m"
_RECON_MEMBER = "PublicMM1/matlab/coef2object.m"


def _verified_bytes(path: Path, sha256: str, limit: int) -> bytes:
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("An explicit SHA-256 is required for every input asset.")
    if not 0 < path.stat().st_size <= limit:
        raise ValueError("Input asset exceeds its bounded byte budget.")
    data = path.read_bytes()
    if len(data) > limit or hashlib.sha256(data).hexdigest() != sha256.lower():
        raise ValueError("Input asset SHA-256 mismatch; parsing was not attempted.")
    return data


def _load_original(data: bytes) -> tuple[dict, dict, dict]:
    try:
        from scipy.io import loadmat, whosmat
    except ImportError as error:
        raise ValueError("The offline BFM converter requires optional SciPy.") from error

    selected = (_MODEL_MEMBER, _ATTR_MEMBER, _EXAMPLE_MEMBER, _RECON_MEMBER)
    raw = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r|gz") as archive:
        count, total = 0, 0
        for member in archive:
            count, total = count + 1, total + member.size
            if count > 1000 or total > _MAX_TAR_BYTES:
                raise ValueError("BFM archive exceeds the bounded decompressed budget.")
            name = member.name
            if name not in selected:
                continue
            if name in raw or not member.isfile():
                raise ValueError("BFM archive has a linked or ambiguous selected member.")
            limit = 256 * 1024**2 if name == _MODEL_MEMBER else 1024**2
            if not 0 < member.size <= limit:
                raise ValueError("Selected BFM archive member exceeds its byte budget.")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Selected BFM member cannot be read.")
            raw[name] = stream.read(limit + 1)
            if len(raw[name]) != member.size:
                raise ValueError("Selected BFM member length is inconsistent.")
    if set(raw) != set(selected):
        raise ValueError("BFM archive is missing a required selected member.")
    # Inspect declared dimensions before asking SciPy to allocate numeric arrays.
    # Allow twice the single/double width to account conservatively for complex
    # declarations; complex values are subsequently rejected by _numeric.
    declared_bytes = 0
    expected_names = (
        (_MODEL_MEMBER, {"shapePC", "shapeEV", "texPC", "texEV"}),
        (_ATTR_MEMBER, {"age_shape", "age_tex"}),
    )
    for member_name, names in expected_names:
        variables = whosmat(io.BytesIO(raw[member_name]))
        declared = [(name, shape, kind) for name, shape, kind in variables if name in names]
        if len(variables) > 1000 or {name for name, _, _ in declared} != names:
            raise ValueError("BFM MAT metadata is missing required arrays or exceeds its budget.")
        if len(declared) != len(names):
            raise ValueError("BFM MAT metadata contains ambiguous required arrays.")
        for name, shape, kind in declared:
            if kind not in {"single", "double"} or len(shape) != 2:
                raise ValueError("BFM MAT selected arrays require plain bounded numeric matrices.")
            if name.endswith("PC"):
                valid = shape[1] == 199 and 9 <= shape[0] <= 3 * _MAX_VERTICES
            elif name.endswith("EV"):
                valid = shape == (199, 1)
            else:
                valid = shape == (200, 1)
            if not valid:
                raise ValueError("BFM MAT selected array dimensions are outside their bounds.")
            declared_bytes += shape[0] * shape[1] * (8 if kind == "single" else 16)
        if declared_bytes > 512 * 1024**2:
            raise ValueError(
                "BFM MAT declared numeric arrays exceed the bounded allocation budget."
            )
    model = loadmat(
        io.BytesIO(raw[_MODEL_MEMBER]),
        variable_names=["shapePC", "shapeEV", "texPC", "texEV"],
        verify_compressed_data_integrity=True,
    )
    attrs = loadmat(
        io.BytesIO(raw[_ATTR_MEMBER]),
        variable_names=["age_shape", "age_tex"],
        verify_compressed_data_integrity=True,
    )
    return model, attrs, {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}


def _target_arrays(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 32
            or len({entry.filename for entry in entries}) != len(entries)
            or sum(entry.file_size for entry in entries) > _MAX_TARGET_BYTES
        ):
            raise ValueError("Cropped BFM NPZ exceeds its safe decompressed budget.")
    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        names = ("u", "w_shp", "tri", "keypoints")
        if not set(names).issubset(archive.files):
            raise ValueError("Cropped BFM is missing required numeric arrays.")
        return {name: archive[name] for name in names}


def _numeric(value: object, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real numbers.")
    return array


def derive_age_arrays(model: dict, attrs: dict, target: dict) -> tuple[dict, dict]:
    """Prove exact first-40 PCA vertex correspondence, then map all-199 directions.

    A vertex signature includes all XYZ coordinates across all 40 supplied PCs.
    This is an exact comparison of numeric values, with no nearest-neighbor,
    fitted scale, projection into 40 coefficients, or use of the UV indices.
    """
    shape_pc = _numeric(model.get("shapePC"), "shapePC")
    if (
        shape_pc.dtype != np.float32
        or shape_pc.ndim != 2
        or shape_pc.shape[1] != 199
        or shape_pc.shape[0] % 3
        or not 3 <= shape_pc.shape[0] // 3 <= _MAX_VERTICES
    ):
        raise ValueError("Original shapePC must be a bounded float32 (3N,199) matrix.")
    full_vertices = shape_pc.shape[0] // 3
    tex_pc = _numeric(model.get("texPC"), "texPC")
    if tex_pc.shape != shape_pc.shape:
        raise ValueError("Original texture and shape bases must use the same 199-dimensional mesh.")
    for name in ("shapeEV", "texEV"):
        value = _numeric(model.get(name), name)
        if value.shape != (199, 1) or np.any(value <= 0):
            raise ValueError("Original PCA standard deviations must be positive (199,1) vectors.")
    for name in ("age_shape", "age_tex"):
        if _numeric(attrs.get(name), name).shape != (200, 1):
            raise ValueError("Original age attributes must preserve their documented 200 entries.")
    mean = _numeric(target.get("u"), "u")
    if mean.ndim != 2 or mean.shape[1] != 1 or mean.shape[0] % 3:
        raise ValueError("Cropped BFM mean must be a (3N,1) matrix.")
    count = mean.shape[0] // 3
    if not 3 <= count <= min(full_vertices, _MAX_VERTICES):
        raise ValueError("Cropped BFM vertex count is outside the bounded original model.")
    cut_pc = _numeric(target.get("w_shp"), "w_shp")
    if cut_pc.dtype != np.float32 or cut_pc.shape != (3 * count, 40):
        raise ValueError("Cropped BFM shape basis must be exactly float32 (3N,40).")
    source = np.ascontiguousarray(shape_pc[:, :40].reshape(-1, 3, 40))
    cropped = np.ascontiguousarray(cut_pc.reshape(-1, 3, 40))
    row_type = np.dtype((np.void, source.dtype.itemsize * 120))
    source_keys = source.reshape(full_vertices, 120).view(row_type).ravel()
    crop_keys = cropped.reshape(count, 120).view(row_type).ravel()
    order = np.argsort(source_keys)
    sorted_keys = source_keys[order]
    if np.any(sorted_keys[1:] == sorted_keys[:-1]):
        raise ValueError("Original PCA vertex correspondence is ambiguous.")
    positions = np.searchsorted(sorted_keys, crop_keys)
    if np.any(positions >= len(sorted_keys)) or not np.array_equal(
        sorted_keys[np.minimum(positions, len(sorted_keys) - 1)], crop_keys
    ):
        raise ValueError("Exact original-to-cropped PCA vertex correspondence is missing.")
    indices = order[positions]
    if len(np.unique(indices)) != count or not np.array_equal(source[indices], cropped):
        raise ValueError("Exact original-to-cropped PCA mapping is not one-to-one.")
    triangles = np.asarray(target.get("tri"))
    coordinates = np.asarray(target.get("keypoints"))
    if (
        triangles.dtype.kind not in "iu"
        or triangles.ndim != 2
        or triangles.shape[1] != 3
        or not 1 <= len(triangles) <= 200_000
        or np.any(triangles < 0)
        or np.any(triangles >= count)
        or np.any(np.diff(np.sort(triangles, axis=1), axis=1) == 0)
        or coordinates.dtype.kind not in "iu"
        or coordinates.shape != (204,)
        or np.any(coordinates < 0)
        or np.any(coordinates >= 3 * count)
    ):
        raise ValueError("Cropped BFM topology and native keypoint coordinates are invalid.")
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for array in (
        np.array([count, len(triangles)], dtype="<i8"),
        triangles.astype("<i8"),
        coordinates.reshape(68, 3).astype("<i8"),
    ):
        digest.update(array.tobytes(order="C"))
    arrays = {"source_vertex_indices": indices.astype(np.int32)}
    for kind, basis_name, ev_name, attr_name in (
        ("shape", "shapePC", "shapeEV", "age_shape"),
        ("texture", "texPC", "texEV", "age_tex"),
    ):
        # Equivalent to the archive's coef2object(alpha + strength*attribute).
        coefficients = model[ev_name].ravel().astype(np.float64) * attrs[attr_name][:199].ravel()
        delta = (np.asarray(model[basis_name], dtype=np.float64) @ coefficients).reshape(-1, 3)
        value = np.asarray(delta[indices], dtype=np.float32)
        if not np.isfinite(value).all() or not np.any(value):
            raise ValueError("Derived age direction must be finite, nonzero float32 data.")
        arrays[f"{kind}_direction"] = value
    report = {
        "original_vertices": full_vertices,
        "vertex_count": count,
        "triangle_count": len(triangles),
        "topology_sha256": digest.hexdigest(),
        "pca_correspondence": {"components": 40, "unique_vertices": count, "max_abs_error": 0},
        "attribute_components_used": 199,
        "attribute_entry_200": "ignored exactly as official apply_attributes.m; semantics unproven",
    }
    return arrays, report


def prepare_bfm_age(
    *,
    bfm_archive: Path,
    bfm_archive_sha256: str,
    target_bfm: Path,
    target_bfm_sha256: str,
    output_dir: Path,
) -> dict:
    """Write only new research assets after all input pins and mapping checks pass."""
    bfm_archive, target_bfm, output_dir = map(Path, (bfm_archive, target_bfm, output_dir))
    targets = (output_dir / "age_direction.npz", output_dir / "provenance.json")
    if any(path.exists() for path in targets):
        raise ValueError("Refusing to overwrite existing BFM age research outputs.")
    # Verify both inputs before any TAR, MAT or NPZ decoding.
    source_data = _verified_bytes(bfm_archive, bfm_archive_sha256, _MAX_ARCHIVE_BYTES)
    target_data = _verified_bytes(target_bfm, target_bfm_sha256, _MAX_TARGET_BYTES)
    model, attrs, members = _load_original(source_data)
    arrays, details = derive_age_arrays(model, attrs, _target_arrays(target_data))
    metadata = {
        "format": FORMAT,
        "source_sha256": bfm_archive_sha256.lower(),
        "target_bfm_sha256": target_bfm_sha256.lower(),
        "topology_sha256": details["topology_sha256"],
        "unit": "bfm_attribute_strength",
        "years_calibrated": False,
    }
    report = {
        **metadata,
        **details,
        "research_only": True,
        "g3_accepted": False,
        "strength_range": [-50, 50],
        "positive_direction": "Older in official apply_attributes.m example",
        "coordinate_system": "bfm_model_raw",
        "sources": {
            "details_url": "https://www.faces.dmi.unibas.ch/bfm/index.php?id=details&nav=1-1-0",
            "original_archive_members": members,
        },
        "formula": "direction = (PC @ (EV * age_attribute[:199])).reshape(-1,3)[vertex_map]",
        "calendar_year_scale": "not established; native strength cannot be used as age years",
    }
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer, **arrays, **{name: np.array(value) for name, value in metadata.items()}
    )
    payload = buffer.getvalue()
    report["output"] = {"path": "age_direction.npz", "sha256": hashlib.sha256(payload).hexdigest()}
    output_dir.mkdir(parents=True, exist_ok=True)
    owned = []
    try:
        for path, data in (
            (targets[0], payload),
            (targets[1], json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")),
        ):
            with path.open("xb") as stream:
                owned.append(path)
                stream.write(data)
    except BaseException:
        for path in owned:
            path.unlink(missing_ok=True)
        raise
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bfm-archive", type=Path, required=True)
    parser.add_argument("--bfm-archive-sha256", required=True)
    parser.add_argument("--target-bfm", type=Path, required=True)
    parser.add_argument("--target-bfm-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare_bfm_age(**vars(args))
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
