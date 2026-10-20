"""Offline 3DDFA sparse-landmark to FFHQ alignment bridge.

Use the backend environment, not the independent SAM environment. This probe
never runs SAM, calibrates age, registers generated pixels to UV, or enables
service capabilities. Projected 3DDFA landmarks are model estimates, not an
independent landmark ground truth.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path
from time import perf_counter

_BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

import numpy as np
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.model_assets import ModelAssetError, load_verified_manifest
from agemorph3d.model_lifecycle import detector_selftest, reconstructor_selftest
from PIL import Image, ImageDraw

_BACKENDS = {"detector": "yolov5_face_onnx", "reconstructor": "3ddfa_v2_onnx"}
_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_SAFE_DETAILS = {
    "NO_FACE": "未检测到人脸，请使用清晰的单人照片。",
    "MULTI_FACE": "需要且只能有一张人脸。",
    "MODEL_ASSET_ERROR": "模型角色、许可、清单或资产完整性检查失败。",
    "BAD_INPUT": "输入图片无效或无法解码。",
    "INPUT_TOO_LARGE": "输入图片文件或像素总量超过限制。",
    "UNSUPPORTED_MEDIA_TYPE": "仅支持内容与扩展名一致的 JPEG、PNG 或 WebP 图片。",
    "OUTPUT_EXISTS": "输出目录已经存在，请使用全新的目录。",
    "OUTPUT_WRITE_FAILED": "无法独占写入输出文件，已清理本次拥有的部分文件。",
    "PROBE_FAILED": "桥接研究失败，请核对输入、模型及对齐条件。",
}


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _png(rgb: np.ndarray) -> bytes:
    result = io.BytesIO()
    with Image.fromarray(rgb) as image:
        image.save(result, format="PNG")
    return result.getvalue()


def _overlay(rgb: np.ndarray, points: np.ndarray, *, roi=None) -> bytes:
    result = io.BytesIO()
    with Image.fromarray(rgb) as image:
        draw = ImageDraw.Draw(image)
        radius = max(1, round(min(image.size) / 256))
        for x, y in points:
            # Avoid passing arbitrarily large model estimates to the rasterizer.
            if (
                -radius <= x < image.width + radius
                and -radius <= y < image.height + radius
            ):
                draw.ellipse(
                    (x - radius, y - radius, x + radius, y + radius), fill=(255, 50, 50)
                )
        if roi is not None:
            left, top, right, bottom = roi
            clipped = (
                max(0, min(image.width - 1, left)),
                max(0, min(image.height - 1, top)),
                max(0, min(image.width - 1, right)),
                max(0, min(image.height - 1, bottom)),
            )
            draw.rectangle(clipped, outline=(20, 255, 60), width=radius)
        image.save(result, format="PNG")
    return result.getvalue()


def _manifest_digest(path: Path) -> str:
    # Manifests are small JSON; reject unbounded input before the existing verifier.
    with path.open("rb") as stream:
        data = stream.read(1024 * 1024 + 1)
    if not data or len(data) > 1024 * 1024:
        raise ModelAssetError("Invalid manifest size.")
    return hashlib.sha256(data).hexdigest()


def probe(args: argparse.Namespace, report: dict) -> dict[str, bytes]:
    from agemorph3d.ffhq_alignment import align_ffhq, transform_points
    from agemorph3d.images import decode_image
    from agemorph3d.static_probe import _construct_model
    from agemorph3d.tddfa import project_vertices

    models = {}
    try:
        report["stage"] = "input"
        settings = Settings()
        with args.image.open("rb") as stream:
            data = stream.read(settings.max_image_bytes + 1)
        if len(data) > settings.max_image_bytes:
            raise ApiError(413, "INPUT_TOO_LARGE", _SAFE_DETAILS["INPUT_TOO_LARGE"])
        with decode_image(
            data, _MEDIA_TYPES.get(args.image.suffix.lower(), ""), settings
        ) as image:
            rgb = np.asarray(image).copy()
        report["input"] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "width": int(rgb.shape[1]),
            "height": int(rgb.shape[0]),
            "orientation": "EXIF-transposed RGB; coordinates refer to this decoded image",
        }

        report["stage"] = "models"
        for role, path in (
            ("detector", args.detector_manifest),
            ("reconstructor", args.reconstructor_manifest),
        ):
            manifest_sha = _manifest_digest(path)
            assets = load_verified_manifest(
                path, research_allow_unresolved=args.research_allow_unresolved
            )
            if assets.manifest.backend != _BACKENDS[role]:
                raise ModelAssetError("Wrong model role.")
            if _manifest_digest(path) != manifest_sha:
                raise ModelAssetError("Manifest changed during verification.")
            model = _construct_model(role, assets)
            models[role] = model
            if (
                model.provider != "CPUExecutionProvider"
                or model.license_verified != assets.license_verified
            ):
                raise ModelAssetError("Wrong model provider or verification state.")
            started = perf_counter()
            (detector_selftest if role == "detector" else reconstructor_selftest)(model)
            report["models"][role] = {
                "model_id": assets.manifest.model_id,
                "backend": assets.manifest.backend,
                "manifest_sha256": manifest_sha,
                "artifacts": [
                    {
                        "role": artifact.role,
                        "sha256": artifact.sha256,
                        "bytes": artifact.size_bytes,
                    }
                    for artifact in assets.manifest.artifacts
                ],
                "license_verified": assets.license_verified,
                "provider": model.provider,
                "operator_selftest": "passed",
                "operator_selftest_ms": (perf_counter() - started) * 1000,
            }

        report["stage"] = "detection"
        faces = models["detector"].detect(rgb)
        report["face_count"] = len(faces)
        if not faces:
            raise ApiError(422, "NO_FACE", _SAFE_DETAILS["NO_FACE"])
        if len(faces) != 1:
            raise ApiError(422, "MULTI_FACE", _SAFE_DETAILS["MULTI_FACE"])

        report["stage"] = "reconstruction"
        raw = models["reconstructor"].reconstruct(rgb, faces[0].bbox)
        projected = project_vertices(raw, models["reconstructor"].keypoint_coordinates)
        if projected.shape != (68, 3) or not np.isfinite(projected).all():
            raise ValueError("Invalid projected sparse landmarks.")
        source_points = projected[:, :2].astype(np.float64)

        report["stage"] = "alignment"
        started = perf_counter()
        aligned = align_ffhq(rgb, source_points, output_size=256)
        aligned_points = transform_points(source_points, aligned.source_to_aligned)
        returned = transform_points(aligned_points, aligned.aligned_to_source)
        recovered_quad = transform_points(
            transform_points(aligned.source_quad, aligned.source_to_aligned),
            aligned.aligned_to_source,
        )
        landmark_error = float(np.abs(returned - source_points).max())
        quad_error = float(np.abs(recovered_quad - aligned.source_quad).max())
        if (
            not np.isfinite([landmark_error, quad_error]).all()
            or max(landmark_error, quad_error) > 1e-6
        ):
            raise ValueError("Alignment coordinate roundtrip failed.")
        coordinates = {
            "source_space": report["input"]["orientation"],
            "landmark_source": "3DDFA/BFM projected iBUG-order 68-point estimates",
            "independent_ground_truth": False,
            "source_size": [int(rgb.shape[1]), int(rgb.shape[0])],
            "aligned_size": [256, 256],
            "coordinate_convention": "zero-based pixel centers; x right, y down",
            "half_pixel_convention": (
                "source_quad maps to output pixel boundaries -0.5 and 255.5; "
                "output integer centers sample quad at (u+0.5)/256, (v+0.5)/256; "
                "equivalent to Pillow QUAD source_quad+0.5; no extra offset applied"
            ),
            "source_points": source_points.tolist(),
            "aligned_points": aligned_points.tolist(),
            "source_to_aligned": aligned.source_to_aligned.tolist(),
            "aligned_to_source": aligned.aligned_to_source.tolist(),
            "source_quad": aligned.source_quad.tolist(),
            "source_quad_order": [
                "top_left",
                "bottom_left",
                "bottom_right",
                "top_right",
            ],
            "roundtrip_max_source_pixels": landmark_error,
            "quad_roundtrip_max_source_pixels": quad_error,
            "alignment_metadata": aligned.metadata,
        }
        report["alignment"] = {
            "output_size": [256, 256],
            "valid_pixels": int(aligned.valid_mask.sum()),
            "total_pixels": int(aligned.valid_mask.size),
            "valid_fraction": float(aligned.valid_mask.mean()),
            "roundtrip_max_source_pixels": landmark_error,
            "quad_roundtrip_max_source_pixels": quad_error,
            "alignment_ms": (perf_counter() - started) * 1000,
            "metadata": aligned.metadata,
        }
        report["reconstruction"] = {
            "topology_sha256": raw.topology_sha256,
            "source_roi": [float(value) for value in raw.roi],
            "source_roi_convention": "3DDFA floating [left, top, right, bottom] source rectangle",
            "crop_120_exported": False,
            "crop_note": "ROI overlay only; no private preprocessing tensor is exported as a 120px crop",
            "projected_landmarks_are_independent_ground_truth": False,
        }
        payloads = {
            "source-landmarks.png": _overlay(rgb, source_points),
            "source-roi.png": _overlay(rgb, source_points, roi=raw.roi),
            "aligned.png": _png(aligned.rgb),
            "valid-mask.png": _png(aligned.valid_mask.astype(np.uint8) * 255),
            "aligned-landmarks.png": _overlay(aligned.rgb, aligned_points),
            "coordinates.json": _json_bytes(coordinates),
        }
        report["artifacts"] = {
            name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in payloads.items()
        }
        return payloads
    finally:
        for model in models.values():
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001, S110 - dispose every owned adapter without exposing internals
                    pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--detector-manifest", type=Path, required=True)
    parser.add_argument("--reconstructor-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args(argv)
    report = {
        "scope": "offline 3DDFA projected-landmark to FFHQ alignment bridge",
        "technical_execution": "failed",
        "service_ready": False,
        "g3_complete": False,
        "years_calibrated": False,
        "identity_accepted": False,
        "uv_registered": False,
        "sam_executed": False,
        "research_allow_unresolved": args.research_allow_unresolved,
        "models": {},
        "stage": "output_directory",
    }
    created = []
    directory_created = False
    try:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        directory_created = True
        try:
            payloads = probe(args, report)
        except Exception as error:  # noqa: BLE001 - safe offline boundary, no exception/path echo
            code = error.code if isinstance(error, ApiError) else "PROBE_FAILED"
            if isinstance(error, ModelAssetError):
                code = "MODEL_ASSET_ERROR"
            report.update(
                error_code=code,
                detail=_SAFE_DETAILS.get(code, _SAFE_DETAILS["PROBE_FAILED"]),
            )
            payloads, exit_code = {}, 1
        else:
            report.update(technical_execution="passed", stage="complete")
            exit_code = 0
        payloads["report.json"] = _json_bytes(report)
        for name, content in payloads.items():
            with (args.output_dir / name).open("xb") as stream:
                created.append(args.output_dir / name)
                stream.write(content)
    except (OSError, ValueError) as error:
        for path in created:
            path.unlink(missing_ok=True)
        code = (
            "OUTPUT_EXISTS"
            if isinstance(error, FileExistsError) and not directory_created
            else "OUTPUT_WRITE_FAILED"
        )
        report.update(
            error_code=code,
            detail=_SAFE_DETAILS[code],
            technical_execution="failed",
            stage="output_write" if directory_created else "output_directory",
        )
        report.pop("artifacts", None)
        exit_code = 1
        if directory_created:
            try:
                with (args.output_dir / "report.json").open("xb") as stream:
                    stream.write(_json_bytes(report))
            except OSError:
                pass
    print(
        json.dumps(
            {
                "technical_execution": report["technical_execution"],
                "service_ready": False,
                "g3_complete": False,
                "error_code": report.get("error_code"),
            },
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
