"""v1.2 request semantics are validated even before successful GLB publication."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from agemorph3d.app import create_app
from agemorph3d.config import Settings


def photo():
    output = BytesIO()
    with Image.new("RGB", (16, 16), "blue") as image:
        image.save(output, format="PNG")
    return ("photo.png", output.getvalue(), "image/png")


@pytest.mark.parametrize("value", [None, "20", "42.5", "70", "70.000"])
def test_optional_user_source_age_reaches_unimplemented_pipeline(value):
    fields = {"source_age": value} if value is not None else {}
    with TestClient(create_app(Settings()), base_url="http://127.0.0.1") as client:
        response = client.post("/api/reconstruct", files={"image": photo()}, data=fields)
    assert response.status_code == 503
    assert response.json()["code"] == "MODEL_NOT_READY"


@pytest.mark.parametrize(
    "value",
    ["", "19.9", "70.1", "NaN", "Infinity", "true", "1e2", " 30", "+30", "３０", "3" * 33],
)
def test_source_age_is_bounded_plain_decimal_and_error_does_not_echo_input(value):
    with TestClient(create_app(Settings()), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/reconstruct",
            files={"image": photo()},
            data={"source_age": value},
        )
    assert response.status_code == 422
    assert response.json()["code"] == "BAD_INPUT"
    assert "mesh_id" not in response.json()


def test_source_age_does_not_relax_file_count_or_unknown_fields():
    with TestClient(create_app(Settings()), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/reconstruct",
            files={"image": photo()},
            data={"source_age": "35", "extra": "private"},
        )
    assert response.status_code == 400
    assert "private" not in response.text


def test_openapi_declares_required_result_semantics_and_optional_source_age():
    schema = create_app(Settings()).openapi()
    operation = schema["paths"]["/api/reconstruct"]["post"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Reconstruction",
    }
    body = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert body["required"] == ["image"]
    assert "source_age" in body["properties"] and body["additionalProperties"] is False
    result = schema["components"]["schemas"]["Reconstruction"]
    assert {"asset_mode", "capabilities", "source_age", "topology_id"} <= set(result["required"])
