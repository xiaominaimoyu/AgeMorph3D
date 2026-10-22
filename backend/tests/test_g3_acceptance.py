"""G3 policy keeps research assessments separate from production authority."""

import json
from dataclasses import FrozenInstanceError

import pytest
from agemorph3d.g3_acceptance import (
    CHECK_IDS,
    COMMON_REQUIREMENTS,
    COMPONENT_REQUIREMENTS,
    SERVICE_REQUIREMENTS,
    Check,
    evaluate_g3,
)


def passed_checks():
    return {
        check_id: Check(
            "passed", "Caller reviewed evidence within its declared scope.", (check_id,)
        )
        for check_id in CHECK_IDS
    }


def test_missing_input_is_explicit_and_never_opens_a_capability():
    report = evaluate_g3({})
    assert set(report["checks"]) == set(CHECK_IDS)
    assert all(check["status"] == "missing" for check in report["checks"].values())
    assert all(not component["accepted"] for component in report["components"].values())
    assert report["service"]["status"] == "missing"
    assert report["candidate_capabilities"] == {"age_morph": False, "age_texture": False}
    assert report["g3_complete"] is False
    assert report["production_enabled"] is False
    assert len(report["components"]["identity"]["blockers"]) == len(COMMON_REQUIREMENTS)
    json.dumps(report, allow_nan=False)


def test_all_assessments_pass_is_only_an_offline_candidate():
    report = evaluate_g3(passed_checks())
    assert report["g3_complete"] is True
    assert report["production_enabled"] is False
    assert report["candidate_capabilities"] == {"age_morph": True, "age_texture": True}
    for group in (*report["components"].values(), report["service"]):
        assert group["status"] == "passed" and group["accepted"] is True
        assert group["blockers"] == []


@pytest.mark.parametrize("check_id", COMMON_REQUIREMENTS)
@pytest.mark.parametrize("status", ["missing", "failed"])
def test_common_prerequisites_block_every_component_and_service(check_id, status):
    checks = passed_checks()
    checks[check_id] = Check(status, "Shared prerequisite is unavailable.", ("review",))
    report = evaluate_g3(checks)
    for group in (*report["components"].values(), report["service"]):
        assert group["status"] == status
        assert not group["accepted"]
        assert group["blockers"] == [
            {
                "check_id": check_id,
                "status": status,
                "reason": "Shared prerequisite is unavailable.",
                "evidence": ["review"],
            }
        ]
    assert not report["g3_complete"]
    assert not any(report["candidate_capabilities"].values())


def test_static_shape_fallback_does_not_disable_an_independently_accepted_texture():
    checks = passed_checks()
    checks["shape_route"] = Check("failed", "Only the static shape fallback is supported.", ("n3",))
    report = evaluate_g3(checks)
    assert report["components"]["shape"]["status"] == "failed"
    assert report["components"]["texture"]["accepted"]
    assert report["candidate_capabilities"] == {"age_morph": False, "age_texture": True}
    assert not report["g3_complete"]
    assert not report["production_enabled"]


def test_mask_rendering_failure_blocks_texture_and_continuity_but_not_shape():
    checks = passed_checks()
    checks["rendered_texture_continuity"] = Check(
        "failed", "MASK support changes despite numeric interpolation convergence.", ("n5",)
    )
    report = evaluate_g3(checks)
    assert report["components"]["shape"]["accepted"]
    assert report["components"]["texture"]["status"] == "failed"
    assert report["components"]["continuity"]["status"] == "failed"
    assert report["candidate_capabilities"] == {"age_morph": True, "age_texture": False}
    assert not report["g3_complete"]


@pytest.mark.parametrize("check_id", ["shape_source_reset", "texture_source_reset"])
def test_missing_original_source_reset_blocks_corresponding_output_and_continuity(check_id):
    checks = passed_checks()
    del checks[check_id]
    report = evaluate_g3(checks)
    target = "shape" if check_id == "shape_source_reset" else "texture"
    assert report["components"][target]["status"] == "missing"
    assert report["components"]["continuity"]["status"] == "missing"
    assert not report["g3_complete"]


def test_failure_takes_precedence_without_losing_missing_evidence():
    checks = passed_checks()
    checks["shape_route"] = Check("failed", "Route comparison retained static geometry.", ("n3",))
    del checks["shape_quality"]
    report = evaluate_g3(checks)
    shape = report["components"]["shape"]
    assert shape["status"] == "failed"
    assert [(item["check_id"], item["status"]) for item in shape["blockers"]] == [
        ("shape_route", "failed"),
        ("shape_quality", "missing"),
    ]


@pytest.mark.parametrize(
    "check_id", [item for item in SERVICE_REQUIREMENTS if item not in COMMON_REQUIREMENTS]
)
def test_service_must_pass_even_when_all_quality_components_pass(check_id):
    checks = passed_checks()
    checks[check_id] = Check(
        "failed", "Only synthetic service evidence is available.", ("fixture",)
    )
    report = evaluate_g3(checks)
    assert all(component["accepted"] for component in report["components"].values())
    assert all(report["candidate_capabilities"].values())
    assert report["service"]["status"] == "failed"
    assert not report["g3_complete"]
    assert not report["production_enabled"]


def test_report_retains_exact_caller_assessments_without_reinterpreting_missing_as_failure():
    check = Check("missing", "Evaluation weights have not been obtained.", ("asset-register",))
    report = evaluate_g3({"identity_quality": check})
    assert report["checks"]["identity_quality"] == {
        "status": "missing",
        "reason": check.reason,
        "evidence": ["asset-register"],
    }


def test_checks_and_fixed_policy_are_immutable_and_output_is_detached():
    checks = passed_checks()
    with pytest.raises(FrozenInstanceError):
        checks["shape_route"].status = "failed"
    with pytest.raises(TypeError):
        COMPONENT_REQUIREMENTS["shape"] = ()
    report = evaluate_g3(checks)
    report["checks"]["shape_route"]["evidence"].append("untrusted-output-edit")
    report["components"]["shape"]["required_checks"].clear()
    repeat = evaluate_g3(checks)
    assert repeat["checks"]["shape_route"]["evidence"] == ["shape_route"]
    assert repeat["components"]["shape"]["required_checks"]


def test_input_order_does_not_change_the_report():
    checks = passed_checks()
    assert evaluate_g3(checks) == evaluate_g3(dict(reversed(list(checks.items()))))


@pytest.mark.parametrize("status", [True, False, None, 1, "PASS", "ready", [], {}])
def test_status_is_explicit_and_never_coerced(status):
    with pytest.raises(ValueError, match="status"):
        Check(status, "Assessment", ("evidence",))


@pytest.mark.parametrize("reason", [None, True, 1, "", " \n", "x" * 2001, "a\x00b"])
def test_reason_requires_bounded_nonempty_text(reason):
    with pytest.raises(ValueError, match="reason"):
        Check("missing", reason)


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_decisive_assessment_requires_evidence(status):
    with pytest.raises(ValueError, match="require evidence"):
        Check(status, "Assessment")


@pytest.mark.parametrize("evidence", [[], ["a"], None, "id", tuple(str(i) for i in range(65))])
def test_evidence_collection_is_bounded_and_immutable(evidence):
    with pytest.raises(ValueError, match="tuple"):
        Check("missing", "Assessment", evidence)


@pytest.mark.parametrize("evidence_id", [None, True, 1, "", " \n", "x" * 129, "a\x00b"])
def test_evidence_ids_require_bounded_nonempty_text(evidence_id):
    with pytest.raises(ValueError, match="Evidence IDs"):
        Check("missing", "Assessment", (evidence_id,))


def test_duplicate_evidence_references_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        Check("passed", "Assessment", ("same", "same"))


@pytest.mark.parametrize("checks", [None, [], True, ("shape_route",)])
def test_policy_requires_a_mapping(checks):
    with pytest.raises(ValueError, match="mapping"):
        evaluate_g3(checks)


@pytest.mark.parametrize("check_id", ["production_enabled", "identity", "shape", "typo", 1, None])
def test_unrecognized_check_ids_cannot_be_silently_ignored(check_id):
    with pytest.raises(ValueError, match="Unknown"):
        evaluate_g3({check_id: Check("passed", "Assessment", ("proof",))})


@pytest.mark.parametrize("value", [True, "passed", None, {"status": "passed"}])
def test_assessments_require_validated_check_instances(value):
    with pytest.raises(ValueError, match="Check instances"):
        evaluate_g3({"shape_route": value})
