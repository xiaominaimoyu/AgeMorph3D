"""Offline one-photo canonical GLB research; never grants service readiness or G1."""

import argparse
import hashlib
import json
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .config import Settings
from .errors import ApiError
from .images import decode_image
from .model_assets import ModelAssetError, load_verified_manifest
from .model_lifecycle import detector_selftest, reconstructor_selftest
from .reconstruction import reconstruct_static
from .schemas import SourceAge

_OUTPUT_NAMES = ("mesh.glb", "result.json", "report.json")
_BACKENDS = {"detector": "yolov5_face_onnx", "reconstructor": "3ddfa_v2_onnx"}
_SAFE_DETAILS = {
    "NO_FACE": "未检测到人脸，请使用清晰的单人照片。",
    "MULTI_FACE": "检测到多张人脸，请上传只有一人的照片。",
    "BAD_INPUT": "图片内容无效或无法解码。",
    "INPUT_TOO_LARGE": "图片文件或像素总量超过限制。",
    "UNSUPPORTED_MEDIA_TYPE": "仅支持内容与声明一致的 JPEG、PNG 或 WebP 图片。",
    "RECONSTRUCTION_FAILED": "人脸重建失败，请检查模型并更换清晰照片后重试。",
}


def _construct_model(role: str, assets: object) -> object:
    # Optional CPU dependencies are loaded only after strict/explicit research verification.
    if role == "detector":
        from .detector import Yolo5FaceOnnx

        return Yolo5FaceOnnx(assets)
    from .tddfa import TddfaOnnx

    return TddfaOnnx(assets)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def probe(args: argparse.Namespace, report: dict) -> tuple[bytes, dict]:
    """Use the real service reconstruction function with independent offline ownership."""
    source_age = SourceAge.from_form(args.source_age)
    models = {}
    try:
        for role, path in (
            ("detector", args.detector_manifest),
            ("reconstructor", args.reconstructor_manifest),
        ):
            started = perf_counter()
            assets = load_verified_manifest(
                path, research_allow_unresolved=args.research_allow_unresolved
            )
            if assets.manifest.backend != _BACKENDS[role]:
                raise ModelAssetError("Model backend does not match its configured role.")
            report["models"][role] = {
                "model_id": assets.manifest.model_id,
                "backend": assets.manifest.backend,
                "revision": assets.manifest.revision,
                "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "license_verified": assets.license_verified,
                "manifest_verification_ms": (perf_counter() - started) * 1000,
            }
            started = perf_counter()
            model = _construct_model(role, assets)
            models[role] = model
            report["models"][role]["load_ms"] = (perf_counter() - started) * 1000
            if model.provider != "CPUExecutionProvider" or (
                model.license_verified != assets.license_verified
            ):
                raise ValueError("Unexpected model provider or license state.")
            report["models"][role]["provider"] = model.provider
            started = perf_counter()
            (detector_selftest if role == "detector" else reconstructor_selftest)(model)
            report["models"][role]["selftest_ms"] = (perf_counter() - started) * 1000
            report["models"][role]["operator_selftest"] = "passed"
        report["license_verified"] = all(
            model["license_verified"] for model in report["models"].values()
        )
        settings = Settings()
        if args.image.stat().st_size > settings.max_image_bytes:
            raise ApiError(413, "INPUT_TOO_LARGE", _SAFE_DETAILS["INPUT_TOO_LARGE"])
        data = args.image.read_bytes()
        report["input"] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(args.image.suffix.lower(), "")
        import numpy as np

        started = perf_counter()
        with decode_image(data, media_type, settings) as image:
            rgb = np.asarray(image).copy()
        report["input"].update(
            width=int(rgb.shape[1]),
            height=int(rgb.shape[0]),
            coordinates="EXIF-corrected original RGB pixels; x right, y down; unmirrored",
        )
        report["timings_ms"]["image_decode"] = (perf_counter() - started) * 1000
        started = perf_counter()
        prepared = reconstruct_static(rgb, models["detector"], models["reconstructor"], source_age)
        report["timings_ms"]["reconstruction_and_glb"] = (perf_counter() - started) * 1000
        result = prepared.result.model_copy(update={"mesh_id": "offline_research"})
        glb = prepared.glb
        if (
            len(glb) < 28
            or glb[:4] != b"glTF"
            or struct.unpack_from("<I", glb, 4)[0] != 2
            or struct.unpack_from("<I", glb, 8)[0] != len(glb)
            or glb[16:20] != b"JSON"
        ):
            raise ValueError("Reconstruction did not produce a standalone GLB.")
        json_length = struct.unpack_from("<I", glb, 12)[0]
        document = json.loads(glb[20 : 20 + json_length])
        report["geometry"] = {
            "topology_id": result.topology_id,
            "vertex_count": document["accessors"][0]["count"],
            "triangle_count": document["accessors"][2]["count"] // 3,
            "coordinate_metadata": document["extras"]["coordinate_metadata"],
            "position_bounds": {
                "min": document["accessors"][0]["min"],
                "max": document["accessors"][0]["max"],
            },
            "normal_source": "unit area-weighted vertex normals from canonical winding",
            "glb_bytes": len(glb),
            "glb_sha256": hashlib.sha256(glb).hexdigest(),
            "morph_targets": False,
            "texture": False,
        }
        report["source_age"] = source_age.model_dump(mode="json")
        return glb, result.model_dump(mode="json")
    finally:
        for model in models.values():
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


def _failure(report: dict, error: Exception) -> None:
    code = error.code if isinstance(error, ApiError) else "PROBE_FAILED"
    if isinstance(error, ModelAssetError):
        code, detail = "MODEL_ASSET_ERROR", "模型资产、哈希或许可核验失败。"
    else:
        detail = _SAFE_DETAILS.get(code, "离线静态重建失败，请检查本机资产、依赖及输入。")
        if code not in _SAFE_DETAILS:
            code = "PROBE_FAILED"
    report.update(
        technical_execution="failed",
        error_type=type(error).__name__,
        error_code=code,
        detail=detail,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector-manifest", type=Path, required=True)
    parser.add_argument("--reconstructor-manifest", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-age", help="Optional user-provided decimal age from 20 to 70.")
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args(argv)
    report = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "B2/B3 offline real-model static research; not service readiness or G1 acceptance",
        "research_allow_unresolved": args.research_allow_unresolved,
        "service_ready": False,
        "g1_complete": False,
        "license_verified": False,
        "models": {},
        "timings_ms": {},
        "technical_execution": "failed",
    }
    created = []
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if any((args.output_dir / name).exists() for name in _OUTPUT_NAMES):
            report.update(
                error_code="OUTPUT_EXISTS", detail="输出目录已有结果，请使用新的输出目录。"
            )
            print(_json_bytes(report).decode("utf-8"), end="")
            return 1
        try:
            glb, result = probe(args, report)
        except Exception as error:
            _failure(report, error)
            payloads = {"report.json": _json_bytes(report)}
            exit_code = 1
        else:
            report["technical_execution"] = "passed"
            payloads = {
                "mesh.glb": glb,
                "result.json": _json_bytes(result),
                "report.json": _json_bytes(report),
            }
            exit_code = 0
        for name, payload in payloads.items():
            path = args.output_dir / name
            with path.open("xb") as stream:
                created.append(path)
                stream.write(payload)
    except (OSError, ValueError):
        # Remove only paths this invocation created; never overwrite a prior success.
        for path in created:
            path.unlink(missing_ok=True)
        report.update(
            technical_execution="failed",
            error_type="OutputWriteError",
            error_code="OUTPUT_WRITE_FAILED",
            detail="无法独占写入输出文件，请检查新的输出目录。",
        )
        exit_code = 1
    print(
        json.dumps(
            {
                "technical_execution": report["technical_execution"],
                "service_ready": False,
                "g1_complete": False,
                "license_verified": report["license_verified"],
                "error_code": report.get("error_code"),
            },
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
