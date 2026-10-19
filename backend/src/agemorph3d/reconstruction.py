"""One-photo static reconstruction, without publishing assets in the worker."""

from dataclasses import dataclass

from .errors import ApiError
from .schemas import Pose, Reconstruction, ResultCapabilities, SourceAge


@dataclass(frozen=True)
class PreparedReconstruction:
    glb: bytes
    result: Reconstruction


def reconstruct_static(
    rgb: object, detector: object, reconstructor: object, source_age: SourceAge
) -> PreparedReconstruction:
    """Require exactly one real detection and preserve its identity/expression."""
    from .static_mesh import build_static_mesh

    try:
        faces = detector.detect(rgb)
        if not isinstance(faces, list):
            raise ValueError("Unexpected detector output.")
        if not faces:
            raise ApiError(422, "NO_FACE", "未检测到人脸，请使用清晰的单人照片。")
        if len(faces) != 1:
            raise ApiError(422, "MULTI_FACE", "检测到多张人脸，请上传只有一人的照片。")
        raw = reconstructor.reconstruct(rgb, faces[0].bbox)
        mesh = build_static_mesh(raw, source_age.model_dump())
        # Validate before publication. This internal identifier is never returned.
        result = Reconstruction(
            mesh_id="unpublished",
            topology_id=mesh.topology_id,
            asset_mode="static",
            capabilities=ResultCapabilities(age_morph=False, age_texture=False),
            source_age=source_age,
            shape=raw.shape.tolist(),
            expr=raw.expr.tolist(),
            pose=Pose.model_validate(mesh.pose),
            texture_url=None,
        )
        return PreparedReconstruction(glb=mesh.glb, result=result)
    except ApiError:
        raise
    except Exception:
        # Model/library errors may contain local paths or photo details.
        raise ApiError(
            500, "RECONSTRUCTION_FAILED", "人脸重建失败，请更换清晰照片后重试。"
        ) from None
