"""Offline FG-NET decode/detect/3DDFA research check.

This is a measurement harness, not a readiness gate. It reuses the service's
decoder, YOLO5Face ONNX adapter and 3DDFA ONNX adapter on the FG-NET 20-70
subset, records failures per image, and compares the 68 projected landmarks
with the landmark files shipped by the FG-NET mirror.

FG-NET is a research-only mirror with unresolved redistribution terms; the
3DDFA/BFM assets are also license-unresolved. The output therefore stays
research-only, never enters ``backend/model-manifests/`` and never changes the
service age capabilities.

The FG-NET ``.pts`` order is not the iBUG 68-point order used by 3DDFA (for
example, the first contour starts and ends near the temples). The primary
metric is therefore order-independent nearest-neighbour deviation, and the
matched error uses an empirically inferred one-to-one mapping that is reported
with its own stability. Neither metric is a calibrated identity or age score.

Usage:
    python tools/fgnet_pipeline_check.py \
        --dataset-root data/datasets/fgnet \
        --detector-manifest data/models/yolov5n05-face/manifest.json \
        --reconstructor-manifest data/models/3ddfa-v2/manifest.json \
        --output-dir output/research/fgnet-pipeline-20261020 \
        --research-allow-unresolved
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

_BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

import numpy as np  # noqa: E402
from agemorph3d.config import Settings  # noqa: E402
from agemorph3d.detector import Yolo5FaceOnnx  # noqa: E402
from agemorph3d.errors import ApiError  # noqa: E402
from agemorph3d.images import decode_image  # noqa: E402
from agemorph3d.model_assets import load_verified_manifest  # noqa: E402
from agemorph3d.tddfa import TddfaOnnx, project_vertices  # noqa: E402

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_CSV_FIELDS = (
    "subject_id",
    "age",
    "image",
    "status",
    "width",
    "height",
    "grayscale",
    "faces",
    "confidence",
    "max_raw_score",
    "detect_ms",
    "reconstruct_ms",
    "proj_in_frame",
    "iod_px",
    "nn_mean_px",
    "nn_mean_iod",
    "matched_nme_px",
    "matched_nme_iod",
    "detail",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_points(path: Path) -> np.ndarray:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    if (
        len(lines) < 71
        or lines[0] != "version: 1"
        or lines[1] != "n_points: 68"
        or lines[2] != "{"
        or lines[-1] != "}"
    ):
        raise ValueError("Unexpected FG-NET .pts header or trailer.")
    try:
        points = np.array(
            [[float(value) for value in line.split()] for line in lines[3:71]],
            dtype=np.float64,
        )
    except ValueError as error:
        raise ValueError("FG-NET .pts contains a non-numeric coordinate.") from error
    if points.shape != (68, 2) or not np.isfinite(points).all():
        raise ValueError("FG-NET .pts must contain 68 finite (x, y) pairs.")
    return points


def _load_rows(csv_path: Path, root: Path) -> list[dict[str, object]]:
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != (
            "subject_id",
            "age",
            "image",
            "sha256",
            "size_bytes",
        ):
            raise ValueError("Unexpected FG-NET subset CSV schema.")
        rows = []
        for raw in reader:
            image = (root / raw["image"]).resolve()
            if not image.is_relative_to(root.resolve()) or not image.is_file():
                raise ValueError(
                    f"CSV image is missing or escapes the dataset root: {raw['image']}"
                )
            rows.append(
                {
                    "subject_id": raw["subject_id"],
                    "age": int(raw["age"]),
                    "image": image,
                    "relative": raw["image"],
                    "sha256": raw["sha256"],
                    "size_bytes": int(raw["size_bytes"]),
                }
            )
    if not rows:
        raise ValueError("FG-NET subset CSV is empty.")
    return rows


def _decade(age: int) -> str:
    lower = age - age % 10
    return f"{lower}-{lower + 9}"


def _row(sample: dict[str, object]) -> dict[str, object]:
    return {
        "subject_id": sample["subject_id"],
        "age": sample["age"],
        "image": sample["relative"],
        "status": "not_run",
        "width": "",
        "height": "",
        "grayscale": "",
        "faces": "",
        "confidence": "",
        "max_raw_score": "",
        "detect_ms": "",
        "reconstruct_ms": "",
        "proj_in_frame": "",
        "iod_px": "",
        "nn_mean_px": "",
        "nn_mean_iod": "",
        "matched_nme_px": "",
        "matched_nme_iod": "",
        "detail": "",
        "_proj": None,
        "_gt": None,
    }


def _raw_max_score(detector: Yolo5FaceOnnx, rgb: np.ndarray) -> float | str:
    """Re-read the decoded head before thresholding; only used for missed faces.

    This is a diagnostic for failure classification, not a second detector: the
    score is the product of objectness and face probability at the best
    candidate, before the production 0.5 threshold is applied.
    """
    from agemorph3d.detector import letterbox  # noqa: PLC0415

    tensor, _ = letterbox(rgb)
    output = np.asarray(
        detector.session.run([detector.output_name], {detector.input_name: tensor})[0]
    )
    if (
        output.ndim != 3
        or output.shape[0] != 1
        or output.shape[2] != 16
        or not np.isfinite(output).all()
    ):
        return ""
    scores = output[0, :, 4] * output[0, :, 15]
    if not np.isfinite(scores).all() or scores.size == 0:
        return ""
    return float(scores.max())


def _evaluate(
    sample: dict[str, object],
    detector: Yolo5FaceOnnx,
    reconstructor: TddfaOnnx,
    settings: Settings,
    points_by_stem: dict[str, Path],
) -> dict[str, object]:
    row = _row(sample)
    image_path = sample["image"]
    assert isinstance(image_path, Path)

    try:
        data = image_path.read_bytes()
    except OSError:
        row.update(status="read_error", detail="OSError")
        return row
    if len(data) != sample["size_bytes"] or hashlib.sha256(data).hexdigest() != sample["sha256"]:
        row.update(status="hash_mismatch", detail="CSV size or SHA-256 does not match")
        return row

    media_type = _MEDIA_TYPES.get(image_path.suffix.lower())
    if media_type is None:
        row.update(status="decode_error", detail="UNSUPPORTED_SUFFIX")
        return row
    try:
        with decode_image(data, media_type, settings) as image:
            rgb = np.asarray(image).copy()
    except ApiError as error:
        row.update(status="decode_error", detail=error.code)
        return row
    except Exception as error:  # noqa: BLE001 - one bad sample must not stop the sweep
        row.update(status="decode_error", detail=type(error).__name__)
        return row

    row["width"], row["height"] = int(rgb.shape[1]), int(rgb.shape[0])
    channel_spread = float(
        max(
            np.abs(rgb[..., 0].astype(np.int16) - rgb[..., 1]).mean(),
            np.abs(rgb[..., 1].astype(np.int16) - rgb[..., 2]).mean(),
        )
    )
    row["grayscale"] = channel_spread < 1.0

    started = perf_counter()
    try:
        faces = detector.detect(rgb)
    except Exception as error:  # noqa: BLE001 - record decoder/detector failures per sample
        row.update(status="detect_error", detect_ms=(perf_counter() - started) * 1000)
        row["detail"] = type(error).__name__
        return row
    row["detect_ms"] = (perf_counter() - started) * 1000
    row["faces"] = len(faces)
    if not faces:
        row["max_raw_score"] = _raw_max_score(detector, rgb)
        row.update(status="no_face")
        return row
    if len(faces) > 1:
        row.update(status="multi_face", confidence=max(face.confidence for face in faces))
        return row

    face = faces[0]
    row["confidence"] = face.confidence
    started = perf_counter()
    try:
        raw = reconstructor.reconstruct(rgb, face.bbox)
        projected = project_vertices(raw, reconstructor.keypoint_coordinates)[:, :2]
    except Exception as error:  # noqa: BLE001 - record regressor/projection failures per sample
        row.update(status="reconstruct_error", reconstruct_ms=(perf_counter() - started) * 1000)
        row["detail"] = type(error).__name__
        return row
    row["reconstruct_ms"] = (perf_counter() - started) * 1000

    height, width = rgb.shape[:2]
    inside = (
        (projected[:, 0] >= 0)
        & (projected[:, 0] <= width - 1)
        & (projected[:, 1] >= 0)
        & (projected[:, 1] <= height - 1)
    )
    row["proj_in_frame"] = float(inside.mean())

    eye_left = np.asarray(face.landmarks[0], dtype=np.float64)
    eye_right = np.asarray(face.landmarks[1], dtype=np.float64)
    iod = float(np.linalg.norm(eye_left - eye_right))
    row["iod_px"] = iod

    points_path = points_by_stem.get(image_path.stem.lower())
    if points_path is None:
        row.update(status="reconstructed_no_reference", detail="missing .pts")
        return row
    try:
        reference = _read_points(points_path)
    except (OSError, ValueError) as error:
        row.update(status="reconstructed_no_reference", detail=type(error).__name__)
        return row

    distances = np.linalg.norm(projected[:, None, :] - reference[None, :, :], axis=2)
    nearest = distances.min(axis=1)
    row["nn_mean_px"] = float(nearest.mean())
    if iod > 0 and np.isfinite(iod):
        row["nn_mean_iod"] = float(nearest.mean() / iod)
    row["_proj"] = projected
    row["_gt"] = reference
    row.update(status="ok")
    return row


def _permutation(rows: list[dict[str, object]]) -> dict[str, object]:
    usable = [row for row in rows if row["_proj"] is not None]
    if not usable:
        return {"available": False}
    assignments = []
    for row in usable:
        projected = row["_proj"]
        reference = row["_gt"]
        assert isinstance(projected, np.ndarray) and isinstance(reference, np.ndarray)
        distances = np.linalg.norm(projected[:, None, :] - reference[None, :, :], axis=2)
        assignments.append(distances.argmin(axis=1))
    matrix = np.stack(assignments)
    mapping = [int(Counter(matrix[:, index].tolist()).most_common(1)[0][0]) for index in range(68)]
    stability = float((matrix == np.asarray(mapping)[None, :]).mean())

    matched = []
    for row in usable:
        projected = row["_proj"]
        reference = row["_gt"]
        iod = row["iod_px"]
        assert isinstance(projected, np.ndarray) and isinstance(reference, np.ndarray)
        distances = np.linalg.norm(projected - reference[mapping], axis=1)
        matched.append(distances.mean())
        row["matched_nme_px"] = float(distances.mean())
        if isinstance(iod, float) and iod > 0:
            row["matched_nme_iod"] = float(distances.mean() / iod)

    array = np.asarray(matched, dtype=np.float64)
    return {
        "available": True,
        "source": "empirical majority of per-image nearest-neighbour assignments",
        "official_fgnet_specification": False,
        "mapping_3ddfa_index_to_fgnet_index": mapping,
        "unique_fgnet_targets": len(set(mapping)),
        "stability": stability,
        "samples": int(array.size),
        "matched_nme_px": {
            "mean": float(array.mean()),
            "median": float(np.median(array)),
            "p90": float(np.percentile(array, 90)),
            "max": float(array.max()),
        },
    }


def _summary(rows: list[dict[str, object]], permutation: dict[str, object]) -> dict[str, object]:
    statuses = Counter(str(row["status"]) for row in rows)
    decided = [row for row in rows if row["status"] != "hash_mismatch"]
    one_face = [row for row in rows if isinstance(row["faces"], int) and row["faces"] == 1]
    referenced = [
        row for row in rows if row["nn_mean_iod"] != "" and row["status"] == "ok"
    ]
    nn = np.asarray([row["nn_mean_iod"] for row in referenced], dtype=np.float64)
    matched = np.asarray(
        [row["matched_nme_iod"] for row in referenced if row["matched_nme_iod"] != ""],
        dtype=np.float64,
    )
    confidence = np.asarray(
        [row["confidence"] for row in one_face], dtype=np.float64
    )
    per_decade = []
    for decade in sorted({_decade(int(row["age"])) for row in rows}):
        subset = [row for row in rows if _decade(int(row["age"])) == decade]
        per_decade.append(
            {
                "decade": decade,
                "images": len(subset),
                "ok": sum(row["status"] == "ok" for row in subset),
                "no_face": sum(row["status"] == "no_face" for row in subset),
                "other_failure": sum(
                    row["status"] not in {"ok", "no_face"} for row in subset
                ),
            }
        )
    return {
        "statuses": dict(sorted(statuses.items())),
        "images": len(rows),
        "subjects": len({row["subject_id"] for row in rows}),
        "decodable_images": len(decided),
        "single_face_images": len(one_face),
        "single_face_rate_of_decodable": len(one_face) / len(decided) if decided else 0.0,
        "reconstructed_with_reference": len(referenced),
        "reconstructed_with_reference_rate": len(referenced) / len(rows) if rows else 0.0,
        "grayscale_images": sum(row["grayscale"] is True for row in rows),
        "one_face_confidence": {
            "mean": float(confidence.mean()),
            "median": float(np.median(confidence)),
            "min": float(confidence.min()),
            "p10": float(np.percentile(confidence, 10)),
        }
        if confidence.size
        else None,
        "order_independent_nn_iod": {
            "mean": float(nn.mean()),
            "median": float(np.median(nn)),
            "p90": float(np.percentile(nn, 90)),
            "max": float(nn.max()),
        }
        if nn.size
        else None,
        "matched_nme_iod": {
            "mean": float(matched.mean()),
            "median": float(np.median(matched)),
            "p90": float(np.percentile(matched, 90)),
            "max": float(matched.max()),
        }
        if matched.size
        else None,
        "by_decade": per_decade,
        "permutation": permutation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=Path("data/datasets/fgnet"))
    parser.add_argument("--subset-csv", type=Path, default=None)
    parser.add_argument("--detector-manifest", type=Path, required=True)
    parser.add_argument("--reconstructor-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer.")
    if not args.research_allow_unresolved:
        parser.error("FG-NET and the 3DDFA/BFM assets are unresolved; pass the research option.")

    root = args.dataset_root.resolve()
    csv_path = (args.subset_csv or root / "adult-20-70.csv").resolve()
    samples = _load_rows(csv_path, root)
    if args.limit is not None:
        samples = samples[: args.limit]

    points_dir = root / "FGNET" / "points"
    points_by_stem = {path.stem.lower(): path for path in points_dir.iterdir() if path.is_file()}

    detector_manifest = args.detector_manifest.resolve()
    reconstructor_manifest = args.reconstructor_manifest.resolve()
    detector_assets = load_verified_manifest(
        detector_manifest, research_allow_unresolved=True
    )
    reconstructor_assets = load_verified_manifest(
        reconstructor_manifest, research_allow_unresolved=True
    )
    if detector_assets.manifest.backend != "yolov5_face_onnx":
        raise SystemExit("detector manifest has the wrong backend")
    if reconstructor_assets.manifest.backend != "3ddfa_v2_onnx":
        raise SystemExit("reconstructor manifest has the wrong backend")

    detector = Yolo5FaceOnnx(detector_assets)
    reconstructor = TddfaOnnx(reconstructor_assets)
    settings = Settings()

    started_at = datetime.now(UTC).isoformat()
    started = perf_counter()
    rows = []
    try:
        for index, sample in enumerate(samples, start=1):
            rows.append(_evaluate(sample, detector, reconstructor, settings, points_by_stem))
            if index % 25 == 0 or index == len(samples):
                print(f"processed {index}/{len(samples)}", flush=True)
    finally:
        for model in (detector, reconstructor):
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - closing must not mask the sweep result
                    pass

    permutation = _permutation(rows)
    report = {
        "schema_version": 1,
        "scope": "offline FG-NET 20-70 decode/detect/3DDFA consistency check",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "age_calibration": False,
        "training_use": False,
        "identity_claim": False,
        "dataset": {
            "dataset_id": "fgnet-research-mirror",
            "subset_csv": csv_path.relative_to(root).as_posix(),
            "subset_csv_sha256": _sha256(csv_path),
            "license_status": "research-only-unresolved",
            "landmark_order": "FG-NET mirror 68-point order, not iBUG 68-point order",
        },
        "models": {
            "detector": {
                "model_id": detector_assets.manifest.model_id,
                "manifest_sha256": _sha256(detector_manifest),
                "license_verified": detector_assets.license_verified,
            },
            "reconstructor": {
                "model_id": reconstructor_assets.manifest.model_id,
                "manifest_sha256": _sha256(reconstructor_manifest),
                "license_verified": reconstructor_assets.license_verified,
            },
        },
        "run": {
            "started_at_utc": started_at,
            "duration_s": perf_counter() - started,
            "samples_requested": len(samples),
            "decoder": "agemorph3d.images.decode_image (EXIF transposed, RGB)",
        },
        "summary": _summary(rows, permutation),
        "failures": [
            {
                "subject_id": row["subject_id"],
                "age": row["age"],
                "image": row["image"],
                "status": row["status"],
                "detail": row["detail"],
                "max_raw_score": row["max_raw_score"],
            }
            for row in rows
            if row["status"] != "ok"
        ],
        "limitations": [
            "Research-only local sweep; no service capability, age calibration or G3 claim.",
            "Metrics describe a 55-subject mirror subset and do not generalize.",
            "FG-NET landmark ordering differs from iBUG; matched NME uses an inferred mapping.",
            "Detector and 3DDFA assets are license-unresolved; service manifests stay strict.",
            "No identity-grouped split or independent evaluation was performed.",
        ],
    }

    export_rows = []
    for row in rows:
        export_rows.append({field: row[field] for field in _CSV_FIELDS})

    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "per-image.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(export_rows)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "images": report["summary"]["images"],
                "single_face_rate": report["summary"]["single_face_rate_of_decodable"],
                "statuses": report["summary"]["statuses"],
            },
            ensure_ascii=False,
        )
    )
    print(f"wrote {args.output_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
