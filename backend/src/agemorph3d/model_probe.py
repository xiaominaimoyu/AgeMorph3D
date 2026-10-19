"""Offline B0 evidence runner. Does not enable any HTTP/WS model capability."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .config import Settings
from .errors import ApiError
from .images import decode_image
from .model_assets import ModelAssetError, load_verified_manifest


def probe(args: argparse.Namespace, report: dict | None = None) -> dict:
    assets = load_verified_manifest(
        args.manifest, research_allow_unresolved=args.research_allow_unresolved
    )
    if report is None:
        report = {}
    report.update(
        {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "scope": "B0 research probe; not service readiness or quality acceptance",
            "model_id": assets.manifest.model_id,
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "assets": assets.manifest.model_dump(mode="json"),
            "license_verified": assets.license_verified,
            "python": platform.python_version(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "onnxruntime", "opencv-python-headless", "pillow")
            },
        }
    )
    # Keep optional inference dependencies out of the model-free API import path.
    import numpy as np

    if args.image.stat().st_size > Settings().max_image_bytes:
        raise ValueError("Probe image exceeds the configured 10 MiB limit.")
    data = args.image.read_bytes()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    with decode_image(data, mime.get(args.image.suffix.lower(), ""), Settings()) as image:
        rgb = np.asarray(image).copy()
    report["image"] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": rgb.shape[1],
        "height": rgb.shape[0],
        "coordinate_system": "EXIF-corrected original RGB pixels; x right, y down; unmirrored",
    }
    started = perf_counter()
    if assets.manifest.backend == "yolov5_face_onnx":
        from .detector import LANDMARK_ORDER, Yolo5FaceOnnx

        model = Yolo5FaceOnnx(assets)
        report["load_ms"] = (perf_counter() - started) * 1000
        started = perf_counter()
        blank_faces = model.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        report["self_test"] = {
            "ms": (perf_counter() - started) * 1000,
            "face_count": len(blank_faces),
        }
        timings = []
        for _ in range(args.runs):
            started = perf_counter()
            faces = model.detect(rgb)
            timings.append((perf_counter() - started) * 1000)
        report.update(
            provider=model.provider,
            input={"name": model.input_name, "shape": [1, 3, 640, 640], "layout": "RGB NCHW /255"},
            output={
                "name": model.output_name,
                "shape": model.session.get_outputs()[0].shape,
                "layout": "decoded xywh,obj,5xy,class; score=obj*class",
            },
            preprocessing={"resize": "letterbox, fixed square, INTER_LINEAR", "padding": 114},
            postprocessing={"confidence_threshold": 0.5, "iou_threshold": 0.45},
            landmark_order=LANDMARK_ORDER,
            landmark_definition=(
                "Native five-point head; image sides observed on frontal sample; "
                "eye center/corner definition unverified"
            ),
            face_count=len(faces),
            detections=[asdict(face) for face in faces],
            detection_ms=timings,
            timing_scope="RGB resize + CPU model + decode/NMS; image file decode excluded",
        )
        if args.save_overlay:
            from PIL import Image, ImageDraw

            with Image.fromarray(rgb) as overlay:
                draw = ImageDraw.Draw(overlay)
                for face in faces:
                    x, y, w, h = face.bbox
                    draw.rectangle((x, y, x + w, y + h), outline="lime", width=2)
                    for index, (x, y) in enumerate(face.landmarks):
                        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill="red")
                        draw.text((x + 3, y + 2), str(index), fill="yellow")
                overlay.save(args.output_dir / "detection.png")
    else:
        from .tddfa import TddfaOnnx, project_vertices

        if args.bbox is None:
            raise ValueError("3DDFA probe requires an explicit original-image --bbox x y w h.")
        model = TddfaOnnx(assets)
        report["load_ms"] = (perf_counter() - started) * 1000
        timings = []
        for _ in range(args.runs):
            started = perf_counter()
            result = model.reconstruct(rgb, args.bbox)
            timings.append((perf_counter() - started) * 1000)
        report.update(
            provider=model.provider,
            input={"shape": [1, 3, 120, 120], "layout": "BGR NCHW (x-127.5)/128"},
            output={
                "shape": [1, 62],
                "layout": "denormalized 12 projection + 40 shape + 10 expression",
            },
            reconstruction_ms=timings,
            timing_scope="ROI/BGR/normalization + CPU regressor + BFM geometry; decode excluded",
            shape_dim=int(result.shape.size),
            expr_dim=int(result.expr.size),
            vertex_count=int(result.vertices.shape[0]),
            triangle_count=int(result.triangles.shape[0]),
            topology_sha256=result.topology_sha256,
            coordinate_system=result.coordinate_system,
            roi=list(result.roi),
            canonical_validated=False,
            uv_validated=False,
            bbox=list(args.bbox),
        )
        projected = project_vertices(result, model.keypoint_coordinates)
        report["projected_landmarks"] = projected[:, :2].tolist()
        report["source_age"] = {"value": None, "method": "unknown"}
        if args.save_geometry:
            np.savez(
                args.output_dir / "raw-reconstruction.npz",
                vertices=result.vertices,
                triangles=result.triangles,
                shape=result.shape,
                expr=result.expr,
                projection=result.projection,
                roi=result.roi,
                keypoint_coordinates=model.keypoint_coordinates,
            )
            report["geometry_file"] = "raw-reconstruction.npz"
        if args.save_overlay:
            from PIL import Image, ImageDraw

            with Image.fromarray(rgb) as overlay:
                draw = ImageDraw.Draw(overlay)
                for x, y in projected[:, :2]:
                    draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill="lime")
                overlay.save(args.output_dir / "reconstruction-landmarks.png")
    report["technical_execution"] = "passed"
    report["b0_complete"] = False  # A single probe does not complete the multi-model gate.
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    parser.add_argument(
        "--save-overlay", action="store_true", help="Save a copy containing the face."
    )
    parser.add_argument(
        "--save-geometry", action="store_true", help="Save private raw reconstruction arrays."
    )
    parser.add_argument("--runs", type=int, choices=range(1, 21), default=3)
    parser.add_argument("--bbox", type=float, nargs=4)
    args = parser.parse_args()
    report = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "b0_complete": False,
        "license_verified": False,
    }
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        report = probe(args, report)
    except ApiError as exc:
        report.update(
            technical_execution="failed",
            error_type="ApiError",
            error_code=exc.code,
            detail=exc.detail,
        )
        exit_code = 1
    except (ModelAssetError, ValueError, OSError, ImportError) as exc:
        # Do not copy library exception messages, which may expose image paths or inputs.
        report.update(
            {
                "technical_execution": "failed",
                "b0_complete": False,
                "error_type": type(exc).__name__,
                "detail": "Check local assets, licenses and inference extras.",
            }
        )
        if isinstance(exc, ModelAssetError):
            report["detail"] = str(exc)
        exit_code = 1
    except Exception as exc:
        report.update(
            {
                "technical_execution": "failed",
                "b0_complete": False,
                "error_type": type(exc).__name__,
                "detail": "Model loading or inference failed.",
            }
        )
        exit_code = 1
    else:
        exit_code = 0
    try:
        encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        (args.output_dir / "report.json").write_text(encoded, encoding="utf-8")
    except (OSError, ValueError):
        report.update(technical_execution="failed", error_type="ReportWriteError")
        exit_code = 1
    print(
        json.dumps(
            {
                "technical_execution": report["technical_execution"],
                "b0_complete": False,
                "license_verified": report.get("license_verified", False),
                "error_type": report.get("error_type"),
            }
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
