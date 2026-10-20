"""Verify local B0 model manifests without downloading or loading model contents."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    UrlConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

ArtifactRole = Literal["detector", "regressor", "bfm", "param_stats", "uv"]
HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]
NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ModelAssetError(ValueError):
    """A manifest or an artifact could not be verified."""


class ModelArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: NonemptyText
    source_url: HttpsUrl
    sha256: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]
    size_bytes: Annotated[int, Field(strict=True, gt=0)]
    role: ArtifactRole

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        windows_path = PureWindowsPath(value)
        normalized = value.replace("\\", "/")
        posix_path = PurePosixPath(normalized)
        if (
            windows_path.drive
            or windows_path.root
            or posix_path.is_absolute()
            or ".." in posix_path.parts
            or posix_path == PurePosixPath(".")
            or "\x00" in normalized
            or ":" in normalized
        ):
            raise ValueError("artifact path must be relative without traversal or drive names")
        return normalized


class AssetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    model_id: NonemptyText
    backend: Literal["yolov5_face_onnx", "3ddfa_v2_onnx"]
    revision: NonemptyText
    code_license: NonemptyText
    code_license_url: HttpsUrl
    weights_license: NonemptyText
    weights_license_url: HttpsUrl
    license_status: Literal["verified", "unresolved"]
    artifacts: Annotated[list[ModelArtifact], Field(min_length=1)]

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def unique_roles(self) -> "AssetManifest":
        roles = [artifact.role for artifact in self.artifacts]
        if len(roles) != len(set(roles)):
            raise ValueError("artifact roles must be unique")
        return self


@dataclass(frozen=True)
class VerifiedModelAssets:
    """Local integrity results; permission claims remain the manifest author's claims."""

    manifest: AssetManifest
    paths: Mapping[ArtifactRole, Path]

    @property
    def license_verified(self) -> bool:
        return self.manifest.license_status == "verified"


def load_verified_manifest(
    path: str | Path, *, research_allow_unresolved: bool = False
) -> VerifiedModelAssets:
    """Check declared provenance, license status, containment, size, and SHA-256.

    This does not independently establish legal permission or load any model. The
    research override permits integrity experiments only; ``license_verified``
    remains false and callers must not promote those assets to service readiness.
    """
    manifest_path = Path(path)
    try:
        manifest = AssetManifest.model_validate_json(manifest_path.read_bytes())
        root = manifest_path.parent.resolve(strict=True)
    except ValidationError as exc:
        # Pydantic's full rendering includes input data, which can contain local paths.
        error_kind = exc.errors(include_input=False)[0]["type"]
        raise ModelAssetError(f"Invalid model asset manifest ({error_kind}).") from None
    except (OSError, RuntimeError, ValueError):
        raise ModelAssetError("Model asset manifest could not be read.") from None

    if not manifest.license_status == "verified" and not research_allow_unresolved:
        raise ModelAssetError("Model weight license is unresolved; verification is required.")

    verified_paths: dict[ArtifactRole, Path] = {}
    for artifact in manifest.artifacts:
        label = f"Artifact '{artifact.role}'"
        try:
            candidate = (root / artifact.path).resolve()
            if not candidate.is_relative_to(root):
                raise ModelAssetError(f"{label} resolves outside the manifest directory.")
            if not candidate.is_file():
                raise ModelAssetError(f"{label} is missing or is not a regular file.")
            digest = hashlib.sha256()
            actual_size = 0
            with candidate.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    actual_size += len(chunk)
                    if actual_size > artifact.size_bytes:
                        raise ModelAssetError(f"{label} size does not match the manifest.")
                    digest.update(chunk)
            if actual_size != artifact.size_bytes:
                raise ModelAssetError(f"{label} size does not match the manifest.")
            if digest.hexdigest() != artifact.sha256.lower():
                raise ModelAssetError(f"{label} SHA-256 does not match the manifest.")
        except (OSError, RuntimeError):
            raise ModelAssetError(f"{label} could not be read or resolved.") from None
        verified_paths[artifact.role] = candidate

    return VerifiedModelAssets(manifest, MappingProxyType(verified_paths))
