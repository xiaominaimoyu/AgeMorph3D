"""Offline B4/B5 native BFM strength and observed-photo UV research.

Strength is not a calendar age. This CLI never enables service capabilities or
claims calibrated years, generated age texture, identity acceptance or G3.
"""

import argparse
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path
from time import perf_counter

from .config import Settings
from .errors import ApiError
from .images import decode_image
from .model_assets import ModelAssetError, load_verified_manifest
from .model_lifecycle import detector_selftest, reconstructor_selftest
from .schemas import SourceAge


def _strengths(value: str) -> list[float]:
    try:
        values = [float(item) for item in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("Strengths must be comma-separated numbers.") from error
    if not 1 <= len(values) <= 9 or any(not math.isfinite(x) or not -50 <= x <= 50 for x in values):
        raise argparse.ArgumentTypeError("Use 1 to 9 finite strengths between -50 and 50.")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("Strengths must be unique.")
    return values


def _pinned_uv(path: Path, pin: str, raw):
    import numpy as np

    if path.suffix.lower() != ".npz" or not 0 < path.stat().st_size <= 8 * 1024**2:
        raise ValueError("UV must be a bounded NPZ.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin.lower():
        raise ValueError("UV hash mismatch.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 8
            or len({entry.filename for entry in entries}) != len(entries)
            or sum(entry.file_size for entry in entries) > 8 * 1024**2
        ):
            raise ValueError("UV archive is ambiguous or oversized.")
    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        uv = archive["uv"].copy()
        if "topology_sha256" in archive:
            binding = archive["topology_sha256"]
            if (
                binding.shape != ()
                or binding.dtype.kind != "U"
                or binding.item() != raw.topology_sha256
            ):
                raise ValueError("UV is bound to a different topology.")
    if (
        uv.dtype.kind not in "iuf"
        or uv.shape != (len(raw.vertices), 2)
        or not np.isfinite(uv).all()
        or np.any(uv < 0)
        or np.any(uv > 1)
    ):
        raise ValueError("Invalid UV correspondence.")
    return np.array(uv, dtype=np.float32)


def _mesh(raw, base, source_age, texture, strength, direction_sha):
    """Use the original canonical frame for every strength, never renormalize aging."""
    import numpy as np

    from .static_mesh import _encode_glb, build_static_mesh

    validated = build_static_mesh(raw, source_age.model_dump(), texture=texture)
    coordinates = base.coordinate_metadata
    vertices = np.asarray(
        (raw.vertices.astype(np.float64) - np.asarray(coordinates["source_center"]))
        * coordinates["source_to_canonical_uniform_scale"],
        dtype=np.float32,
    )
    if not np.isfinite(vertices).all():
        raise ValueError("Nonfinite strength geometry.")
    extras = {
        "asset_mode": "static",
        "source_age": source_age.model_dump(mode="json"),
        "topology_id": base.topology_id,
        "coordinate_metadata": coordinates,
        "attribute_research": {
            "strength": strength,
            "unit": "bfm_attribute_strength",
            "years_calibrated": False,
            "direction_sha256": direction_sha,
            "normalization_reference": "unchanged_source_mesh",
            "age_texture_generated": False,
            "identity_quality_accepted": False,
        },
    }
    if texture is not None:
        extras["base_texture"] = texture.metadata
    return _encode_glb(vertices, validated.normals, validated.triangles, extras, texture)


def probe(args, report) -> dict[str, bytes]:
    source_age = SourceAge.from_form(args.source_age)
    import numpy as np

    from .age_shape import apply_age_strength, load_age_direction
    from .static_mesh import build_static_mesh
    from .static_probe import _construct_model
    from .uv_texture import project_photo_texture

    models, assets_by_role = {}, {}
    payloads = {}
    try:
        for role, path, expected in (
            ("detector", args.detector_manifest, "yolov5_face_onnx"),
            ("reconstructor", args.reconstructor_manifest, "3ddfa_v2_onnx"),
        ):
            assets = load_verified_manifest(
                path, research_allow_unresolved=args.research_allow_unresolved
            )
            if assets.manifest.backend != expected:
                raise ModelAssetError("Wrong model role.")
            model = _construct_model(role, assets)
            models[role], assets_by_role[role] = model, assets
            if (
                model.provider != "CPUExecutionProvider"
                or model.license_verified != assets.license_verified
            ):
                raise ValueError("Wrong provider or verification state.")
            (detector_selftest if role == "detector" else reconstructor_selftest)(model)
            report["models"][role] = {
                "model_id": assets.manifest.model_id,
                "provider": model.provider,
                "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "license_verified": assets.license_verified,
                "operator_selftest": "passed",
            }
        settings = Settings()
        if args.image.stat().st_size > settings.max_image_bytes:
            raise ApiError(413, "INPUT_TOO_LARGE", "图片文件过大。")
        data = args.image.read_bytes()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(args.image.suffix.lower(), "")
        with decode_image(data, mime, settings) as image:
            rgb = np.asarray(image).copy()
        faces = models["detector"].detect(rgb)
        if not faces:
            raise ApiError(422, "NO_FACE", "需要清晰的单人照片。")
        if len(faces) != 1:
            raise ApiError(422, "MULTI_FACE", "照片中需要且只能有一人。")
        raw = models["reconstructor"].reconstruct(rgb, faces[0].bbox)
        report["input"] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "width": int(rgb.shape[1]),
            "height": int(rgb.shape[0]),
        }
        report["source_age"] = source_age.model_dump(mode="json")
        uv = getattr(models["reconstructor"], "uv", None)
        if args.uv is not None:
            uv = _pinned_uv(args.uv, args.uv_sha256, raw)
        texture = None
        if uv is not None:
            started = perf_counter()
            texture = project_photo_texture(rgb, raw, uv)
            report["base_texture"] = dict(
                texture.metadata, projection_ms=(perf_counter() - started) * 1000
            )
            payloads["base-atlas.png"] = texture.png
            bound = io.BytesIO()
            np.savez_compressed(bound, uv=uv, topology_sha256=np.array(raw.topology_sha256))
            payloads["uv_bound.npz"] = bound.getvalue()
            report["uv_asset"] = {
                "input_sha256": args.uv_sha256,
                "output_sha256": hashlib.sha256(bound.getvalue()).hexdigest(),
                "topology_sha256": raw.topology_sha256,
                "production_license_verified": False,
            }
        base = build_static_mesh(raw, source_age.model_dump(), texture=texture)
        direction = None
        if args.direction is not None:
            bfm_pin = next(
                a.sha256
                for a in assets_by_role["reconstructor"].manifest.artifacts
                if a.role == "bfm"
            )
            direction = load_age_direction(
                args.direction, args.direction_sha256, target_bfm_sha256=bfm_pin
            )
            report["direction"] = {
                "sha256": args.direction_sha256,
                "unit": direction.unit,
                "years_calibrated": False,
                "target_bfm_sha256": bfm_pin,
                "topology_sha256": direction.topology_sha256,
            }
        payloads["mesh.glb"] = _mesh(raw, base, source_age, texture, 0, args.direction_sha256)
        result = {
            "mesh_id": "offline_attribute_research",
            "topology_id": base.topology_id,
            "asset_mode": "static",
            "capabilities": {"age_morph": False, "age_texture": False},
            "source_age": source_age.model_dump(mode="json"),
            "shape": raw.shape.tolist(),
            "expr": raw.expr.tolist(),
            "pose": base.pose,
            "texture_url": None,
        }
        payloads["result.json"] = _json(result)
        for index, strength in enumerate(args.strengths):
            modified = (
                apply_age_strength(raw, direction, strength) if direction is not None else raw
            )
            glb = _mesh(modified, base, source_age, texture, strength, args.direction_sha256)
            name = f"strength-{index:02d}.glb"
            payloads[name] = glb
            report["variants"].append(
                {
                    "strength": strength,
                    "file": name,
                    "sha256": hashlib.sha256(glb).hexdigest(),
                    "max_source_displacement": float(
                        np.linalg.norm(
                            modified.vertices.astype(np.float64) - raw.vertices, axis=1
                        ).max()
                    ),
                    "shape_coefficients_unchanged": bool(np.array_equal(raw.shape, modified.shape)),
                    "expression_coefficients_unchanged": bool(
                        np.array_equal(raw.expr, modified.expr)
                    ),
                }
            )
        if direction is not None:
            outward = apply_age_strength(raw, direction, 50)
            returned = apply_age_strength(outward, direction, -50)
            roundtrip = float(np.abs(returned.vertices.astype(np.float64) - raw.vertices).max())
            midpoint = apply_age_strength(raw, direction, 25).vertices.astype(np.float64)
            linearity = float(
                np.abs(midpoint - (outward.vertices.astype(np.float64) + raw.vertices) / 2).max()
            )
            report["numerical_checks"] = {
                "zero_preserves_exact_vertices": apply_age_strength(raw, direction, 0) is raw,
                "roundtrip_max_source_error": roundtrip,
                "roundtrip_max_canonical_error": roundtrip
                * base.coordinate_metadata["source_to_canonical_uniform_scale"],
                "linear_midpoint_max_source_error": linearity,
                "fixed_canonical_frame": True,
                "identity_quality_accepted": False,
            }
        return payloads
    finally:
        for model in models.values():
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


def _json(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector-manifest", type=Path, required=True)
    parser.add_argument("--reconstructor-manifest", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--source-age")
    parser.add_argument("--direction", type=Path)
    parser.add_argument("--direction-sha256")
    parser.add_argument("--uv", type=Path)
    parser.add_argument("--uv-sha256")
    parser.add_argument("--strengths", type=_strengths, default=[0.0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args(argv)
    for field in ("uv", "direction"):
        if (getattr(args, field) is None) != (getattr(args, field + "_sha256") is None):
            parser.error(f"--{field} and --{field}-sha256 are required together")
    if args.uv is not None and not args.research_allow_unresolved:
        parser.error("An independently supplied UV asset requires the explicit research option.")
    if args.direction is None and any(value != 0 for value in args.strengths):
        parser.error("Nonzero native strengths require a pinned direction asset.")
    report = {
        "scope": "offline native BFM attribute strength and observed base-photo UV",
        "technical_execution": "failed",
        "service_ready": False,
        "g3_complete": False,
        "years_calibrated": False,
        "age_texture_generated": False,
        "research_allow_unresolved": args.research_allow_unresolved,
        "models": {},
        "variants": [],
    }
    created = []
    directory_created = False
    try:
        # Exclusive directory creation rejects previous evidence before loading models.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        directory_created = True
        try:
            payloads = probe(args, report)
        except Exception as error:
            code = error.code if isinstance(error, ApiError) else "PROBE_FAILED"
            if isinstance(error, ModelAssetError):
                code = "MODEL_ASSET_ERROR"
            report.update(
                error_code=code, detail="离线研究检查失败，请核对本机资产、许可、哈希及单人照片。"
            )
            payloads, exit_code = {}, 1
        else:
            report["technical_execution"] = "passed"
            exit_code = 0
        payloads["report.json"] = _json(report)
        for name, content in payloads.items():
            with (args.output_dir / name).open("xb") as stream:
                created.append(args.output_dir / name)
                stream.write(content)
    except FileExistsError:
        for path in created:
            path.unlink(missing_ok=True)
        report.update(
            error_code="OUTPUT_WRITE_FAILED" if directory_created else "OUTPUT_EXISTS",
            technical_execution="failed",
        )
        exit_code = 1
    except (OSError, ValueError):
        for path in created:
            path.unlink(missing_ok=True)
        report.update(error_code="OUTPUT_WRITE_FAILED", technical_execution="failed")
        exit_code = 1
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
