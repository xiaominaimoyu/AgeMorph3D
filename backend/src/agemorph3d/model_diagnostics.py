"""Read-only model inventory diagnostics, independent of strict loading/inference.

Run ``python -m agemorph3d.model_diagnostics --help``. This explicit command
hashes configured artifacts even when license registration blocks the loader.
It never changes manifests, opens a port, constructs a model or grants readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from pydantic import ValidationError

from .model_assets import AssetManifest, ModelArtifact
from .model_lifecycle import _BACKENDS

MAX_MANIFEST_BYTES = 64 * 1024
_REQUIRED = {"detector": {"detector"}, "reconstructor": {"regressor", "bfm", "param_stats"}}
_ALLOWED = {"detector": {"detector"}, "reconstructor": _REQUIRED["reconstructor"] | {"uv"}}


def _stamp(path: Path) -> tuple:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _artifact(root: Path, artifact: ModelArtifact) -> dict:
    result = {
        "role": artifact.role,
        "status": "unreadable",
        "expected_size_bytes": artifact.size_bytes,
        "observed_size_bytes": None,
        "observed_sha256": None,
    }
    try:
        path = (root / artifact.path).resolve()
        if not path.is_relative_to(root):
            result["status"] = "outside_manifest_directory"
            return result
        if not path.exists():
            result["status"] = "missing"
            return result
        if not path.is_file():
            result["status"] = "not_regular_file"
            return result
        before = _stamp(path)
        result["observed_size_bytes"] = before[2]
        if before[2] != artifact.size_bytes:
            result["status"] = "size_mismatch"
            return result
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as stream:
            while chunk := stream.read(min(1024 * 1024, artifact.size_bytes - count + 1)):
                count += len(chunk)
                if count > artifact.size_bytes:
                    result.update(status="changed_during_check", observed_size_bytes=count)
                    return result
                digest.update(chunk)
        result["observed_size_bytes"] = count
        if _stamp(path) != before or count != artifact.size_bytes:
            result["status"] = "changed_during_check"
            return result
        result["observed_sha256"] = digest.hexdigest()
        result["status"] = (
            "verified" if digest.hexdigest() == artifact.sha256.lower() else "hash_mismatch"
        )
    except (OSError, RuntimeError, ValueError):
        # No path, manifest text, credential URL or underlying exception is emitted.
        result["status"] = "unreadable"
    return result


def inspect_model(role: str, path: str | Path | None) -> dict:
    """Report independent registration, role and integrity results for one model."""
    if role not in _BACKENDS:
        raise ValueError("Unsupported model role.")
    result = {
        "role": role,
        "configured": path is not None,
        "manifest_status": "unconfigured",
        "manifest_sha256": None,
        "registered_license_status": None,
        "backend_matches_role": False,
        "artifact_roles_match": False,
        "artifacts": [],
        "blocking_reasons": [],
        "strict_load_preconditions_met": False,
        "operator_selftests_run": False,
        "grants_service_readiness": False,
    }
    if path is None:
        result["blocking_reasons"] = ["MANIFEST_NOT_CONFIGURED"]
        return result
    try:
        path = Path(path)
        if path.suffix.lower() != ".json" or not path.is_file():
            result["manifest_status"] = "missing" if not path.exists() else "invalid"
            result["blocking_reasons"] = ["MANIFEST_MISSING_OR_INVALID"]
            return result
        with path.open("rb") as stream:
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            result["manifest_status"] = "oversized"
            result["blocking_reasons"] = ["MANIFEST_TOO_LARGE"]
            return result
        manifest = AssetManifest.model_validate_json(data)
        root = path.parent.resolve(strict=True)
    except (OSError, RuntimeError, ValueError, ValidationError):
        result["manifest_status"] = "invalid"
        result["blocking_reasons"] = ["MANIFEST_MISSING_OR_INVALID"]
        return result
    result.update(
        manifest_status="valid",
        manifest_sha256=hashlib.sha256(data).hexdigest(),
        registered_license_status=manifest.license_status,
        backend_matches_role=manifest.backend == _BACKENDS[role],
    )
    roles = {a.role for a in manifest.artifacts}
    result["artifact_roles_match"] = _REQUIRED[role] <= roles <= _ALLOWED[role]
    result["artifacts"] = [_artifact(root, a) for a in manifest.artifacts]
    if manifest.license_status != "verified":
        result["blocking_reasons"].append("LICENSE_REGISTRATION_UNRESOLVED")
    if not result["backend_matches_role"]:
        result["blocking_reasons"].append("BACKEND_ROLE_MISMATCH")
    if not result["artifact_roles_match"]:
        result["blocking_reasons"].append("ARTIFACT_ROLE_SET_MISMATCH")
    if any(a["status"] != "verified" for a in result["artifacts"]):
        result["blocking_reasons"].append("ARTIFACT_INTEGRITY_FAILED")
    try:
        with path.open("rb") as stream:
            final = stream.read(MAX_MANIFEST_BYTES + 1)
        if final != data:
            result["manifest_status"] = "changed_during_check"
            result["blocking_reasons"].append("MANIFEST_CHANGED_DURING_CHECK")
    except (OSError, RuntimeError):
        result["manifest_status"] = "unreadable"
        result["blocking_reasons"].append("MANIFEST_CHANGED_DURING_CHECK")
    result["strict_load_preconditions_met"] = not result["blocking_reasons"]
    return result


def diagnose(detector_manifest=None, reconstructor_manifest=None) -> dict:
    models = [
        inspect_model("detector", detector_manifest),
        inspect_model("reconstructor", reconstructor_manifest),
    ]
    passed = all(m["strict_load_preconditions_met"] for m in models)
    return {
        "schema_version": 1,
        "operation": "model_asset_diagnostics",
        "status": "preconditions_met" if passed else "blocked",
        "models": models,
        "operator_selftests_run": False,
        "model_inference": False,
        "grants_service_readiness": False,
        "observes_running_service": False,
        "permission_assessment": "manifest_registration_only_not_independent_authorization",
        "next_step": "strict_loader_and_operator_selftests_required"
        if passed
        else "resolve_each_reported_registration_role_or_integrity_blocker",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--detector-manifest", type=Path, default=os.environ.get("AGEMORPH_DETECTOR_MANIFEST")
    )
    parser.add_argument(
        "--reconstructor-manifest",
        type=Path,
        default=os.environ.get("AGEMORPH_RECONSTRUCTOR_MANIFEST"),
    )
    args = parser.parse_args(argv)
    result = diagnose(args.detector_manifest, args.reconstructor_manifest)
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2))
    return 0 if result["status"] == "preconditions_met" else 1


if __name__ == "__main__":
    raise SystemExit(main())
