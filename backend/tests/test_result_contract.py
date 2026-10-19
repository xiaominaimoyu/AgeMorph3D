"""Static results cannot inherit age claims from service-wide availability."""

import pytest
from pydantic import ValidationError

from agemorph3d.schemas import Reconstruction, SourceAge


def result(**changes):
    data = {
        "mesh_id": "opaque-subject",
        "topology_id": "bfm-v2-topology",
        "asset_mode": "static",
        "capabilities": {"age_morph": False, "age_texture": False},
        "source_age": {"value": None, "method": "unknown", "calibration_id": None},
        "shape": [0.0] * 40,
        "expr": [0.0] * 10,
        "pose": {"R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0]},
    }
    data.update(changes)
    return data


def test_unknown_age_static_result_has_no_implicit_anchor():
    parsed = Reconstruction.model_validate(result())
    assert parsed.source_age.value is None
    assert parsed.model_dump()["source_age"] == {
        "value": None,
        "method": "unknown",
        "calibration_id": None,
    }
    assert not any(parsed.capabilities.model_dump().values())


def test_multipart_age_is_explicit_user_evidence_not_demo_state():
    assert SourceAge.from_form(None).method == "unknown"
    assert SourceAge.from_form("36.5").model_dump() == {
        "value": 36.5,
        "method": "user",
        "calibration_id": None,
    }


@pytest.mark.parametrize("field", ["asset_mode", "capabilities", "source_age", "topology_id"])
def test_result_semantics_are_required_in_v12(field):
    data = result()
    del data[field]
    with pytest.raises(ValidationError):
        Reconstruction.model_validate(data)


@pytest.mark.parametrize(
    "age",
    [
        {"value": 45, "method": "unknown", "calibration_id": None},
        {"value": None, "method": "user", "calibration_id": None},
        {"value": None, "method": "estimated", "calibration_id": "v1"},
        {"value": 30, "method": "estimated", "calibration_id": None},
        {"value": 30, "method": "user", "calibration_id": "v1"},
        {"value": None, "method": "unknown", "calibration_id": "v1"},
        {"value": True, "method": "user", "calibration_id": None},
        {"value": "30", "method": "user", "calibration_id": None},
        {"value": 19, "method": "user", "calibration_id": None},
        {"value": 71, "method": "user", "calibration_id": None},
        {"value": float("nan"), "method": "user", "calibration_id": None},
        {"value": float("inf"), "method": "user", "calibration_id": None},
    ],
)
def test_source_age_requires_consistent_evidence_and_finite_adult_range(age):
    with pytest.raises(ValidationError):
        SourceAge.model_validate(age)


@pytest.mark.parametrize("age", [20, 45.5, 70])
def test_user_and_calibrated_estimate_are_distinct(age):
    user = SourceAge(value=age, method="user", calibration_id=None)
    estimated = SourceAge(value=age, method="estimated", calibration_id="local-age-v1")
    assert user.value == estimated.value == age
    assert user.calibration_id is None and estimated.calibration_id == "local-age-v1"


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_mode": "age_morph"},
        {"capabilities": {"age_morph": True, "age_texture": False}},
        {"asset_mode": "age_morph", "capabilities": {"age_morph": True, "age_texture": False}},
        {"capabilities": {"age_morph": False, "age_texture": True}},
        {"capabilities": {"age_morph": "false", "age_texture": False}},
        {"capabilities": {"age_morph": False}},
    ],
)
def test_inconsistent_or_incomplete_age_capabilities_are_rejected(changes):
    with pytest.raises(ValidationError):
        Reconstruction.model_validate(result(**changes))


def test_age_texture_can_be_independent_of_age_geometry():
    age = {"value": 36, "method": "user", "calibration_id": None}
    data = result(source_age=age, capabilities={"age_morph": False, "age_texture": True})
    with pytest.raises(ValidationError):
        Reconstruction.model_validate(data)
    data["texture_url"] = "/api/assets/opaque-subject/base.png"
    parsed = Reconstruction.model_validate(data)
    assert parsed.asset_mode == "static" and parsed.capabilities.age_texture


def test_age_morph_result_requires_source_age_but_not_age_texture():
    parsed = Reconstruction.model_validate(
        result(
            asset_mode="age_morph",
            capabilities={"age_morph": True, "age_texture": False},
            source_age={"value": 36, "method": "user", "calibration_id": None},
        )
    )
    assert parsed.texture_url is None and parsed.source_age.value == 36
