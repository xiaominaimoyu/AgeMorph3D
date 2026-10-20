"""Embedded base-photo UV transport; no age-texture or identity accuracy claim."""

import io
import json
import struct
from types import SimpleNamespace

import pytest
from PIL import Image

np = pytest.importorskip("numpy")

from agemorph3d.reconstruction import reconstruct_static  # noqa: E402
from agemorph3d.schemas import SourceAge  # noqa: E402
from agemorph3d.static_mesh import build_static_mesh  # noqa: E402


def raw_face():
    return SimpleNamespace(
        shape=np.zeros(40),
        expr=np.zeros(10),
        vertices=np.array([[-1, -1, 0], [0, 1, 1], [1, -1, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int64),
        projection=np.column_stack((np.eye(3), [12, 12, 0])),
        roi=(0, 0, 24, 24),
        coordinate_system="bfm_model_raw",
        topology_sha256="a" * 64,
    )


def texture():
    rgba = np.array(
        [[[255, 0, 0, 255], [0, 0, 255, 0]], [[0, 255, 0, 255], [255, 255, 0, 255]]], dtype=np.uint8
    )
    buffer = io.BytesIO()
    Image.fromarray(rgba).save(buffer, "PNG")
    return SimpleNamespace(
        png=buffer.getvalue(),
        gltf_uv=np.array([[0, 0], [0, 1], [1, 1]], dtype=np.float32),
        metadata={"kind": "observed_source_photo", "age_texture": False, "coverage": 0.75},
    )


def parse(data):
    size = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + size]), data[28 + size :]


def test_embedded_png_uv_alpha_and_geometry_survive_glb_encoding():
    age = SourceAge.from_form(None)
    plain = build_static_mesh(raw_face(), age.model_dump())
    colored = build_static_mesh(raw_face(), age.model_dump(), texture=texture())
    np.testing.assert_array_equal(colored.vertices, plain.vertices)
    np.testing.assert_array_equal(colored.normals, plain.normals)
    np.testing.assert_array_equal(colored.triangles, plain.triangles)
    assert colored.topology_id == plain.topology_id
    document, binary = parse(colored.glb)
    assert document["buffers"][0]["byteLength"] == len(binary)
    assert document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"] == 3
    accessor = document["accessors"][3]
    view = document["bufferViews"][accessor["bufferView"]]
    uv = np.frombuffer(binary, dtype="<f4", count=6, offset=view["byteOffset"]).reshape(3, 2)
    np.testing.assert_array_equal(uv, texture().gltf_uv)
    view = document["bufferViews"][document["images"][0]["bufferView"]]
    image_bytes = binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]
    assert image_bytes == texture().png
    with Image.open(io.BytesIO(image_bytes)) as image:
        assert image.mode == "RGBA" and image.getpixel((1, 0)) == (0, 0, 255, 0)
    material = document["materials"][0]
    assert material["alphaMode"] == "MASK"
    assert material["pbrMetallicRoughness"]["baseColorFactor"] == [1, 1, 1, 1]
    assert document["extras"]["asset_mode"] == "static"
    assert not document["extras"]["base_texture"]["age_texture"]
    assert all("uri" not in item for item in document["images"] + document["buffers"])


@pytest.mark.parametrize("change", ["uv_count", "uv_nan", "uv_range", "png", "oversized_png"])
def test_incompatible_texture_cannot_be_embedded(change):
    value = texture()
    if change == "uv_count":
        value.gltf_uv = np.zeros((2, 2))
    elif change == "uv_nan":
        value.gltf_uv[0, 0] = np.nan
    elif change == "uv_range":
        value.gltf_uv[0, 0] = 1.1
    elif change == "png":
        value.png = b"invalid-image"
    else:
        value.png = value.png + b"\0" * (16 * 1024**2)
    with pytest.raises(ValueError):
        build_static_mesh(raw_face(), SourceAge.from_form(None).model_dump(), texture=value)


def test_reconstruction_embeds_base_texture_without_enabling_age_capabilities(monkeypatch):
    calls = []
    atlas = texture()

    def project(rgb, raw, uv):
        calls.append((rgb.shape, raw.topology_sha256, uv.shape))
        return atlas

    monkeypatch.setattr("agemorph3d.uv_texture.project_photo_texture", project)
    detector = SimpleNamespace(detect=lambda rgb: [SimpleNamespace(bbox=(1, 1, 20, 20))])
    reconstructor = SimpleNamespace(uv=atlas.gltf_uv, reconstruct=lambda rgb, bbox: raw_face())
    prepared = reconstruct_static(
        np.zeros((24, 24, 3), dtype=np.uint8), detector, reconstructor, SourceAge.from_form("42.5")
    )
    assert calls == [((24, 24, 3), "a" * 64, (3, 2))]
    assert prepared.result.asset_mode == "static" and prepared.result.texture_url is None
    assert prepared.result.capabilities.model_dump() == {"age_morph": False, "age_texture": False}
    assert prepared.result.source_age.value == 42.5
    assert "images" in parse(prepared.glb)[0]
