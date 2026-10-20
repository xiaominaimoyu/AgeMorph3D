"""Local BFM native attribute-strength experiments; no calendar-age prediction.

Only an offline converter's hash-bound, exact-correspondence direction is used.
The 40 identity coefficients and 10 expression coefficients stay untouched.
This module is intentionally independent of production model readiness.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .prepare_bfm_age import FORMAT

if TYPE_CHECKING:
    from .tddfa import TddfaResult

_MAX_BYTES = 8 * 1024**2


@dataclass(frozen=True)
class AgeDirection:
    shape_direction: np.ndarray
    texture_direction: np.ndarray
    source_vertex_indices: np.ndarray
    topology_sha256: str
    target_bfm_sha256: str
    source_sha256: str
    unit: str = "bfm_attribute_strength"
    years_calibrated: bool = False


def load_age_direction(path: Path, sha256: str, *, target_bfm_sha256: str) -> AgeDirection:
    """Load a pinned research NPZ bound to the actual cropped BFM input hash."""
    for value in (sha256, target_bfm_sha256):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("Explicit direction and target BFM SHA-256 pins are required.")
    path = Path(path)
    if path.suffix.lower() != ".npz" or not 0 < path.stat().st_size <= _MAX_BYTES:
        raise ValueError("Age research direction must be a bounded safe NPZ file.")
    data = path.read_bytes()
    if len(data) > _MAX_BYTES or hashlib.sha256(data).hexdigest() != sha256.lower():
        raise ValueError("Age direction SHA-256 mismatch; no arrays were loaded.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 16
            or len({entry.filename for entry in entries}) != len(entries)
            or sum(entry.file_size for entry in entries) > _MAX_BYTES
        ):
            raise ValueError("Age direction NPZ exceeds its safe decompressed budget.")
    keys = {
        "shape_direction",
        "texture_direction",
        "source_vertex_indices",
        "format",
        "source_sha256",
        "target_bfm_sha256",
        "topology_sha256",
        "unit",
        "years_calibrated",
    }
    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        if set(archive.files) != keys:
            raise ValueError("Age direction NPZ has an unexpected research schema.")
        values = {name: archive[name] for name in keys}
    for name in ("format", "source_sha256", "target_bfm_sha256", "topology_sha256", "unit"):
        if values[name].shape != () or values[name].dtype.kind != "U":
            raise ValueError("Age direction metadata must use scalar Unicode strings.")
        values[name] = values[name].item()
    if (
        values["format"] != FORMAT
        or values["unit"] != "bfm_attribute_strength"
        or values["years_calibrated"].dtype != np.bool_
        or values["years_calibrated"].shape != ()
        or values["years_calibrated"].item() is not False
    ):
        raise ValueError("Only uncalibrated native BFM attribute strength is supported.")
    for name in ("source_sha256", "target_bfm_sha256", "topology_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", values[name]):
            raise ValueError("Age direction provenance hashes are invalid.")
    if values["target_bfm_sha256"] != target_bfm_sha256.lower():
        raise ValueError("Age direction was prepared for a different target BFM asset.")
    shape = values["shape_direction"]
    texture = values["texture_direction"]
    indices = values["source_vertex_indices"]
    if (
        shape.dtype != np.float32
        or shape.ndim != 2
        or shape.shape[1] != 3
        or not 3 <= len(shape) <= 100_000
        or not np.isfinite(shape).all()
        or not np.any(shape)
        or texture.dtype != np.float32
        or texture.shape != shape.shape
        or not np.isfinite(texture).all()
        or not np.any(texture)
        or indices.dtype.kind not in "iu"
        or indices.shape != (len(shape),)
        or np.any(indices < 0)
        or np.any(indices >= 100_000)
        or len(np.unique(indices)) != len(indices)
    ):
        raise ValueError("Age direction arrays must be finite, nonzero and one-to-one.")
    for array in (shape, texture, indices):
        array.setflags(write=False)
    return AgeDirection(
        shape,
        texture,
        indices,
        values["topology_sha256"],
        values["target_bfm_sha256"],
        values["source_sha256"],
    )


def apply_age_strength(
    result: TddfaResult, direction: AgeDirection, strength: float
) -> TddfaResult:
    """Add native strength in raw source units, never infer years from source age.

    +/-50 is the bounded range of the original manipulation example. Positive
    strength follows Older; zero returns the input result exactly. The source
    canonical normalization must be reused when comparing different strengths.
    """
    if (
        isinstance(strength, (bool, np.bool_))
        or not isinstance(strength, (int, float, np.integer, np.floating))
        or not math.isfinite(strength)
        or not -50 <= strength <= 50
    ):
        raise ValueError("BFM attribute strength must be a finite number between -50 and 50.")
    if (
        result.coordinate_system != "bfm_model_raw"
        or result.topology_sha256 != direction.topology_sha256
        or direction.unit != "bfm_attribute_strength"
        or direction.years_calibrated is not False
        or result.vertices.dtype != np.float32
        or result.vertices.shape != direction.shape_direction.shape
        or not np.isfinite(result.vertices).all()
        or not np.isfinite(direction.shape_direction).all()
    ):
        raise ValueError("BFM native direction must match this raw source mesh and topology.")
    if strength == 0:
        return result
    # Accumulate in float64; this avoids avoidable drift without mutating input arrays.
    vertices = np.asarray(
        result.vertices.astype(np.float64)
        + float(strength) * direction.shape_direction.astype(np.float64),
        dtype=np.float32,
    )
    if not np.isfinite(vertices).all():
        raise ValueError("BFM strength produces coordinates outside the finite float32 range.")
    vertices.setflags(write=False)
    return replace(result, vertices=vertices)
