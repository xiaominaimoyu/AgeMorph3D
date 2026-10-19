"""Validated v1.2 contracts with explicit asset and result capability semantics."""

import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MeshId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")]
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Coefficient = Annotated[FiniteNumber, Field(ge=-1_000_000, le=1_000_000)]
Coefficients = Annotated[list[Coefficient], Field(min_length=1, max_length=300)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelStatus(ApiModel):
    state: Literal["missing", "loading", "ready", "error"]
    backend: str | None = None
    provider: str | None = None
    detail: str


class Capabilities(ApiModel):
    reconstruction: Annotated[bool, Field(strict=True)] = False
    age_morph: Annotated[bool, Field(strict=True)] = False
    age_texture: Annotated[bool, Field(strict=True)] = False
    realtime: Annotated[bool, Field(strict=True)] = False


class Health(ApiModel):
    models: dict[str, ModelStatus]
    device: str
    version: str
    api_version: Literal["1.2"] = "1.2"
    capabilities: Capabilities = Field(default_factory=Capabilities)


class AgingRequest(ApiModel):
    mesh_id: MeshId
    age: Annotated[FiniteNumber, Field(ge=20, le=70)]


class Pose(ApiModel):
    R: Annotated[list[FiniteNumber], Field(min_length=9, max_length=9)]
    t: Annotated[list[FiniteNumber], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def check_rotation(self) -> "Pose":
        tolerance = 1e-3
        if any(abs(value) > 1 + tolerance for value in self.R):
            raise ValueError("R must be an orthonormal rotation matrix.")
        rows = [self.R[index : index + 3] for index in (0, 3, 6)]
        for first in range(3):
            for second in range(first, 3):
                dot = math.fsum(rows[first][index] * rows[second][index] for index in range(3))
                if abs(dot - (1 if first == second else 0)) > tolerance:
                    raise ValueError("R must be an orthonormal rotation matrix.")
        a, b, c, d, e, f, g, h, i = self.R
        determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        if abs(determinant - 1) > tolerance:
            raise ValueError("R must have determinant +1.")
        return self


class SourceAge(ApiModel):
    value: Annotated[FiniteNumber, Field(ge=20, le=70)] | None
    method: Literal["unknown", "user", "estimated"]
    calibration_id: MeshId | None

    @classmethod
    def from_form(cls, value: str | None) -> "SourceAge":
        """Multipart decimal text is distinct from permissive JSON coercion."""
        if value is None:
            return cls(value=None, method="unknown", calibration_id=None)
        if (
            not isinstance(value, str)
            or len(value) > 32
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)
        ):
            raise ValueError("Source age must be plain decimal text between 20 and 70.")
        return cls(value=float(value), method="user", calibration_id=None)

    @model_validator(mode="after")
    def check_provenance(self) -> "SourceAge":
        if self.method == "unknown":
            if self.value is not None or self.calibration_id is not None:
                raise ValueError("Unknown source age must have null value and calibration_id.")
        elif self.value is None:
            raise ValueError("A user or estimated source age requires a value.")
        if self.method == "estimated":
            if self.calibration_id is None:
                raise ValueError("Estimated source age requires a calibration identifier.")
        elif self.calibration_id is not None:
            raise ValueError("Only estimated source age may declare a calibration identifier.")
        return self


class ResultCapabilities(ApiModel):
    age_morph: Annotated[bool, Field(strict=True)]
    age_texture: Annotated[bool, Field(strict=True)]


class Reconstruction(ApiModel):
    mesh_id: MeshId
    topology_id: MeshId
    asset_mode: Literal["static", "age_morph"]
    capabilities: ResultCapabilities
    source_age: SourceAge
    shape: Coefficients
    expr: Coefficients
    pose: Pose
    texture_url: str | None = None

    @model_validator(mode="after")
    def check_result_capabilities(self) -> "Reconstruction":
        if self.capabilities.age_morph != (self.asset_mode == "age_morph"):
            raise ValueError("Asset mode must agree with this result's age morph capability.")
        if self.capabilities.age_morph or self.capabilities.age_texture:
            if self.source_age.value is None:
                raise ValueError("Absolute age capabilities require a known source age.")
        if self.capabilities.age_texture and self.texture_url is None:
            raise ValueError("Age texture capability requires the result's base texture URL.")
        return self

    @field_validator("texture_url")
    @classmethod
    def check_texture_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(
            r"/api/assets/[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*", value
        ):
            raise ValueError("texture_url must be a relative /api/assets/ file path.")
        if any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("texture_url cannot contain path traversal.")
        return value
