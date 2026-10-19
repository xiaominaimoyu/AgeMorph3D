"""Validated v1.1 service contracts; no synthetic model results."""

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
    api_version: Literal["1.1"] = "1.1"
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


class Reconstruction(ApiModel):
    mesh_id: MeshId
    shape: Coefficients
    expr: Coefficients
    pose: Pose
    texture_url: str | None = None

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
