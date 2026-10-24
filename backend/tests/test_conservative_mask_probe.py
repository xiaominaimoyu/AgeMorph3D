"""Synthetic geometry, protection priority and publication boundaries only."""

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

_PATH = Path(__file__).resolve().parents[2] / "tools/conservative_mask_probe.py"
_SPEC = importlib.util.spec_from_file_location("conservative_mask_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


@pytest.fixture
def annotation():
    return {
        "schema_version": 1,
        "sample_id": "fgnet-004a63--sam-020",
        "target_image": {"path": "prior/target.png", "bytes": 1, "sha256": "a" * 64},
        "source_age_api": {"value": None, "method": "unknown", "calibration_id": None},
        "reviewer_kind": "ai",
        "reviewer": "codex-root-visual-observation",
        "human_review_completed": False,
        "skin_polygons": [[[10, 10], [54, 10], [54, 54], [10, 54]]],
        "protected_polygons": [[[30, 30], [34, 30], [34, 34], [30, 34]]],
        "margin_pixels": 12,
    }


@pytest.fixture
def layers(annotation):
    return probe.rasterize_annotations(annotation, 64, 64)


@pytest.fixture
def old_masks():
    base = np.zeros((64, 64), dtype=bool)
    base[4:60, 4:60] = True
    excluded = np.zeros_like(base)
    excluded[8:56, 8:56] = True
    return base & ~excluded, excluded


def test_native_integer_polygon_edges_are_inclusive_and_margin_has_exact_known_extent(annotation):
    before = copy.deepcopy(annotation)
    result = probe.rasterize_annotations(annotation, 64, 64)
    assert set(result) == {"skin", "protected", "protected_margin"}
    for array in result.values():
        assert array.dtype == np.bool_ and array.shape == (64, 64)
    assert result["skin"].sum() == 45 * 45
    assert result["skin"][10, 10] and result["skin"][54, 54]
    assert not result["skin"][9, 10] and not result["skin"][55, 54]
    assert result["protected"].sum() == 25
    assert result["protected_margin"].sum() == 29 * 29
    assert result["protected_margin"][18, 18] and result["protected_margin"][46, 46]
    assert not result["protected_margin"][17, 18] and not result["protected_margin"][47, 46]
    assert annotation == before


def test_polygon_winding_does_not_change_raster_or_protection(annotation):
    expected = probe.rasterize_annotations(annotation, 64, 64)
    for key in ("skin_polygons", "protected_polygons"):
        annotation[key] = [vertices[::-1] for vertices in annotation[key]]
    actual = probe.rasterize_annotations(annotation, 64, 64)
    for name in expected:
        np.testing.assert_array_equal(actual[name], expected[name])


def test_multiple_polygons_form_a_union_without_even_odd_holes(annotation):
    annotation["skin_polygons"] = [
        [[10, 10], [30, 10], [30, 30], [10, 30]],
        [[20, 20], [40, 20], [40, 40], [20, 40]],
    ]
    result = probe.rasterize_annotations(annotation, 64, 64)
    assert result["skin"].sum() == 2 * 21 * 21 - 11 * 11
    assert result["skin"][25, 25]
    assert not result["skin"][10, 40]


def test_non_self_intersecting_concave_skin_polygon_preserves_its_unselected_notch(annotation):
    annotation["skin_polygons"] = [[[5, 5], [20, 5], [20, 10], [10, 10], [10, 20], [5, 20]]]
    result = probe.rasterize_annotations(annotation, 64, 64)
    assert result["skin"][7, 17] and result["skin"][17, 7]
    assert not result["skin"][17, 17]


def test_protected_margin_clips_at_image_boundary_with_constant_zero_and_no_wrap(annotation):
    annotation["protected_polygons"] = [[[0, 0], [2, 0], [2, 2], [0, 2]]]
    result = probe.rasterize_annotations(annotation, 64, 64)
    assert result["protected"].sum() == 9
    assert result["protected_margin"].sum() == 15 * 15
    assert result["protected_margin"][0, 0] and result["protected_margin"][14, 14]
    assert not result["protected_margin"][15, 0] and not result["protected_margin"][-1].any()
    assert not result["protected_margin"][:, -1].any()


def test_only_explicit_skin_in_old_exclusion_outside_protected_margin_is_released(
    old_masks, layers
):
    allowed, excluded = old_masks
    result = probe.refine_masks(allowed, excluded, layers)
    assert set(result) == {"allowed", "occluded", "labels", "counts"}
    assert result["allowed"].dtype == result["occluded"].dtype == np.bool_
    assert result["labels"].dtype == np.uint8
    assert result["counts"] == {
        "old_allowed_pixels": 832,
        "old_occluded_pixels": 2304,
        "skin_pixels": 2025,
        "protected_pixels": 25,
        "protected_margin_pixels": 841,
        "released_pixels": 1184,
        "protected_old_occluded_pixels": 841,
        "remaining_old_occluded_pixels": 279,
        "new_allowed_pixels": 2016,
        "new_occluded_pixels": 1120,
        "label_pixels": {"0": 1792, "1": 1184, "2": 841, "3": 279},
    }
    assert json.loads(json.dumps(result["counts"], allow_nan=False)) == result["counts"]
    np.testing.assert_array_equal(result["allowed"] | result["occluded"], allowed | excluded)
    assert np.all(result["allowed"][allowed])
    assert not np.any(result["allowed"] & result["occluded"])
    assert not np.any((result["labels"] == 1) & layers["protected_margin"])
    assert result["labels"][0, 0] == 0
    assert result["labels"][10, 10] == 1
    assert result["labels"][30, 30] == 2
    assert result["labels"][8, 8] == 3


def test_protected_priority_holds_even_when_every_old_excluded_pixel_is_annotated_skin(
    old_masks, layers
):
    layers["skin"][:] = True
    allowed, excluded = old_masks
    result = probe.refine_masks(allowed, excluded, layers)
    assert result["counts"]["released_pixels"] == 2304 - 841
    np.testing.assert_array_equal(result["occluded"], excluded & layers["protected_margin"])
    assert result["labels"][30, 30] == 2


def test_absent_skin_never_automatically_releases_the_old_band(old_masks, layers):
    layers["skin"][:] = False
    allowed, excluded = old_masks
    result = probe.refine_masks(allowed, excluded, layers)
    assert result["counts"]["released_pixels"] == 0
    np.testing.assert_array_equal(result["allowed"], allowed)
    np.testing.assert_array_equal(result["occluded"], excluded)


def test_protection_does_not_remove_already_allowed_pixels_or_label_nonexcluded_pixels(
    old_masks, layers
):
    layers["protected"][:] = False
    layers["protected"][5, 5] = True
    layers["protected_margin"][:] = False
    layers["protected_margin"][:18, :18] = True
    allowed, excluded = old_masks
    result = probe.refine_masks(allowed, excluded, layers)
    assert result["allowed"][5, 5] and result["labels"][5, 5] == 0
    assert result["occluded"][10, 10] and result["labels"][10, 10] == 2


def test_skin_outside_old_base_stays_unfilled_and_original_arrays_are_not_modified(
    old_masks, layers
):
    layers["skin"][:] = True
    before = copy.deepcopy((old_masks, layers))
    result = probe.refine_masks(*old_masks, layers)
    assert not result["allowed"][0, 0] and result["labels"][0, 0] == 0
    for now, original in zip(old_masks, before[0], strict=True):
        assert now.tobytes() == original.tobytes()
    for name, array in layers.items():
        assert array.tobytes() == before[1][name].tobytes()


@pytest.mark.parametrize("collection", ["skin_polygons", "protected_polygons"])
@pytest.mark.parametrize(
    "vertices",
    [
        [[10, 10], [20, 20]],
        [[10, 10], [20, 20], [30, 30]],
        [[10, 10], [20, 10], [20, 10], [10, 20]],
        [[10, 10], [20, 10], [20, 20], [10, 10]],
        [[10, 10], [50, 50], [10, 50], [50, 10]],
        [[32, 2], [50, 58], [3, 23], [61, 23], [14, 58]],
        [[10, 10], [50, 10], [50, 50], [30, 10], [10, 50]],
    ],
)
def test_degenerate_duplicate_or_self_intersecting_polygons_are_rejected(
    annotation, collection, vertices
):
    annotation[collection] = [vertices]
    with pytest.raises(ValueError):
        probe.rasterize_annotations(annotation, 64, 64)


@pytest.mark.parametrize("value", [-1, 64, 2**40, 10.5, True, "10", np.nan])
def test_polygon_coordinates_are_bounded_native_integers_without_rounding(annotation, value):
    annotation["skin_polygons"][0][0][0] = value
    with pytest.raises(ValueError):
        probe.rasterize_annotations(annotation, 64, 64)


@pytest.mark.parametrize("problem", ["per_polygon", "total_vertices"])
def test_vertex_budgets_are_enforced_before_raster_allocation(annotation, problem):
    vertices = [[x, 0] for x in range(64)] + [[63, y] for y in range(1, 33)]
    vertices += [[x, 32] for x in range(62, 29, -1)]
    assert len(vertices) == 129 and len({tuple(p) for p in vertices}) == 129
    annotation["skin_polygons"] = [vertices] if problem == "per_polygon" else [vertices[:128]] * 33
    with pytest.raises(ValueError):
        probe.rasterize_annotations(annotation, 64, 64)


@pytest.mark.parametrize("width,height", [(0, 64), (64, 0), (True, 64), (64.0, 64), (5000, 5000)])
def test_raster_bounds_are_validated_before_allocation(annotation, width, height):
    with pytest.raises(ValueError):
        probe.rasterize_annotations(annotation, width, height)


@pytest.mark.parametrize(
    "problem",
    [
        "schema",
        "age_default",
        "human",
        "reviewer_kind",
        "reviewer",
        "margin",
        "path",
        "pin",
        "empty",
        "too_many",
    ],
)
def test_annotation_provenance_and_review_boundaries_cannot_be_relaxed(annotation, problem):
    if problem == "schema":
        annotation["schema_version"] = 2
    elif problem == "age_default":
        annotation["source_age_api"] = {"value": 50, "method": "default", "calibration_id": None}
    elif problem == "human":
        annotation["human_review_completed"] = True
    elif problem == "reviewer_kind":
        annotation["reviewer_kind"] = "human"
    elif problem == "reviewer":
        annotation["reviewer"] = ""
    elif problem == "margin":
        annotation["margin_pixels"] = 11
    elif problem == "path":
        annotation["sample_id"] = "../../different"
    elif problem == "pin":
        annotation["target_image"]["sha256"] = "no hash"
    elif problem == "empty":
        annotation["skin_polygons"] = []
    else:
        annotation["skin_polygons"] *= 65
    with pytest.raises(ValueError):
        probe.rasterize_annotations(annotation, 64, 64)


@pytest.mark.parametrize(
    "problem",
    [
        "old_overlap",
        "old_shape",
        "old_dtype",
        "layer_shape",
        "layer_dtype",
        "missing",
        "unprotected_margin",
        "margin_not_dilated",
    ],
)
def test_refinement_rejects_inconsistent_frames_or_protection_layers(old_masks, layers, problem):
    allowed, excluded = old_masks
    if problem == "old_overlap":
        allowed[30, 30] = True
    elif problem == "old_shape":
        excluded = excluded[:63]
    elif problem == "old_dtype":
        allowed = allowed.astype(np.uint8)
    elif problem == "layer_shape":
        layers["skin"] = layers["skin"][:63]
    elif problem == "layer_dtype":
        layers["skin"] = layers["skin"].astype(np.uint8)
    elif problem == "missing":
        layers.pop("protected")
    elif problem == "unprotected_margin":
        layers["protected_margin"][30, 30] = False
    else:
        layers["protected_margin"][0, 0] = True
    with pytest.raises(ValueError):
        probe.refine_masks(allowed, excluded, layers)


def publication_fixture():
    png = io.BytesIO()
    Image.new("L", (1, 1), 255).save(png, format="PNG")
    payloads = {
        f"masks/fgnet-004a63--sam-{age:03d}-{kind}.png": png.getvalue()
        for age in (20, 45, 63, 70)
        for kind in ("allowed", "occluded", "labels")
    }
    payloads["mask-review.json"] = b'{"synthetic_publication_boundary":true}\n'
    records = [
        {
            "sample_id": f"{source}--sam-{age:03d}",
            "status": "ok",
            "baseline": {"synthetic": True},
            "refinement": {"released_pixels": 1},
            "artifacts": {"synthetic": True},
        }
        for source, ages in probe.uv.COHORT.items()
        for age in ages
    ]
    report = {
        "inputs": [],
        "records": records,
        "artifacts": {"synthetic": True},
        "summary": {"all_requested_verified": True, "requested_targets": 12},
    }
    return payloads, report


def test_successful_publication_writes_whole_batch_and_checks_before_and_after(tmp_path):
    payloads, report = publication_fixture()
    output = tmp_path / "candidate"
    phases = []
    result = probe.publish_batch(
        output, payloads, report, lambda: phases.append((output / "report.json").exists())
    )
    assert phases == [False, True]
    assert result["summary"]["all_requested_verified"] is True
    for name, data in payloads.items():
        assert (output / name).read_bytes() == data
    assert len(list(output.rglob("*.png"))) == 12
    assert json.loads((output / "report.json").read_bytes()) == result


@pytest.mark.parametrize("fail_on", [1, 2])
def test_each_drift_phase_invalidates_every_result_and_removes_only_owned_payloads(
    tmp_path, fail_on
):
    payloads, report = publication_fixture()
    output = tmp_path / "candidate"
    calls = 0

    def audit():
        nonlocal calls
        calls += 1
        if calls == fail_on:
            if output.exists():
                (output / "foreign-note.txt").write_bytes(b"keep unrelated file")
            raise ValueError("synthetic frozen source/annotation/runtime drift")

    result = probe.publish_batch(output, payloads, report, audit)
    assert len(result["records"]) == 12
    assert result["summary"]["all_requested_verified"] is False
    assert result["artifacts"] == {}
    assert all(
        row["status"] == "invalidated_input_drift"
        and row["artifacts"] == {}
        and row.get("refinement") is None
        and "baseline" not in row
        for row in result["records"]
    )
    assert not list(output.rglob("*.png")) and not (output / "mask-review.json").exists()
    if (output / "foreign-note.txt").exists():
        assert (output / "foreign-note.txt").read_bytes() == b"keep unrelated file"
    assert json.loads((output / "report.json").read_bytes()) == result


@pytest.mark.parametrize(
    "problem",
    [
        "missing_mask",
        "foreign_path",
        "escape_path",
        "incomplete_cohort",
        "duplicate_cohort",
        "failure_as_success",
    ],
)
def test_incomplete_or_unbound_publication_is_refused_before_writing(tmp_path, problem):
    payloads, report = publication_fixture()
    if problem == "missing_mask":
        payloads.pop(next(name for name in payloads if name.endswith(".png")))
    elif problem == "foreign_path":
        payloads["arbitrary.txt"] = b"no"
    elif problem == "escape_path":
        payloads["../escape.txt"] = b"no"
    elif problem == "incomplete_cohort":
        report["records"].pop()
    elif problem == "duplicate_cohort":
        report["records"][1]["sample_id"] = report["records"][0]["sample_id"]
    else:
        report["records"][0]["status"] = "failed"
    output = tmp_path / "candidate"
    with pytest.raises(ValueError):
        probe.publish_batch(output, payloads, report, lambda: None)
    assert not output.exists() and not (tmp_path / "escape.txt").exists()


def test_existing_candidate_directory_and_its_foreign_file_are_preserved(tmp_path):
    payloads, report = publication_fixture()
    output = tmp_path / "candidate"
    output.mkdir()
    (output / "foreign-note.txt").write_bytes(b"do not overwrite")
    with pytest.raises((FileExistsError, ValueError)):
        probe.publish_batch(
            output, payloads, report, lambda: pytest.fail("old output entered audit")
        )
    assert (output / "foreign-note.txt").read_bytes() == b"do not overwrite"
    assert sorted(path.name for path in output.iterdir()) == ["foreign-note.txt"]


def test_failed_cohort_can_publish_only_its_failure_report(tmp_path):
    _, report = publication_fixture()
    report["summary"]["all_requested_verified"] = False
    report["artifacts"] = {}
    for row in report["records"]:
        row.update(status="baseline_verified_candidate_blocked", artifacts={}, refinement=None)
    output = tmp_path / "failed-candidate"
    result = probe.publish_batch(output, {}, report, lambda: None)
    assert result["summary"]["all_requested_verified"] is False
    assert sorted(p.name for p in output.iterdir()) == ["report.json"]


def review_fixture(tmp_path):
    def pin(name):
        return {"path": name, "bytes": 1, "sha256": "a" * 64}

    focus = [f"fgnet-004a63--sam-{age:03d}" for age in (20, 45, 63, 70)]
    identifiers = [*focus, *(f"synthetic-control-{number:02d}" for number in range(33))]
    rows = [
        {
            "sample_id": sample_id,
            "input": pin(f"prior/{sample_id}.png"),
            "target_fit": pin(f"prior/{sample_id}.json"),
            "allowed_mask": pin(f"prior/{sample_id}-allowed.png"),
            "occluded_mask": pin(f"prior/{sample_id}-occluded.png"),
            "allowed_pixels": 832,
            "excluded_occluder_pixels": 2304,
            "method": "saved baseline",
            "notes": ["retain historical observation"],
            "exclusions": [{"saved": True}],
            "control_payload": {"nested": [1, None, "保留"]},
            "status": "reviewed_conservative_exclusion",
            "reviewer": "codex_visual_review",
        }
        for sample_id in identifiers
    ]
    original = {
        "schema_version": 1,
        "protocol_id": "agemorph3d-target-uv-v1",
        "target_records": rows,
        "before_atlas_outcomes": True,
    }
    output = tmp_path / "output/research/conservative"
    refinements = {
        sample_id: {
            "refinement": {
                "counts": {
                    "new_allowed_pixels": 2016,
                    "new_occluded_pixels": 1120,
                    "released_pixels": 1184,
                }
            },
            "artifacts": {
                role: pin(f"output/research/conservative/masks/{sample_id}-{role}.png")
                for role in ("allowed", "occluded", "labels")
            },
        }
        for sample_id in focus
    }
    roles = {
        name: pin(f"prior/{name}.json")
        for name in ("protocol", "mask_report", "mask_audit", "uv_report", "annotations")
    }
    return (
        original,
        refinements,
        pin("prior/annotations.json"),
        output,
        roles,
        pin("prior/study-plan.json"),
    )


def test_review_changes_only_four_focus_masks_and_preserves_all33_original_controls(tmp_path):
    original, refinements, annotation_pin, output, roles, plan_pin = review_fixture(tmp_path)
    before = copy.deepcopy(original)
    review, raw = probe._build_review(
        original, refinements, annotation_pin, output, tmp_path, roles, plan_pin
    )
    assert json.loads(raw) == review and len(review["target_records"]) == 37
    assert original == before
    new_rows = {row["sample_id"]: row for row in review["target_records"]}
    for row in before["target_records"]:
        sample_id = row["sample_id"]
        if sample_id not in refinements:
            assert new_rows[sample_id] == row
            continue
        candidate = new_rows[sample_id]
        assert candidate["input"] == row["input"] and candidate["target_fit"] == row["target_fit"]
        assert candidate["allowed_mask"] == refinements[sample_id]["artifacts"]["allowed"]
        assert candidate["occluded_mask"] == refinements[sample_id]["artifacts"]["occluded"]
        assert candidate["allowed_pixels"] == 2016 and candidate["excluded_occluder_pixels"] == 1120
        assert candidate["status"] == "reviewed_conservative_exclusion"
        assert candidate["reviewer"] == "codex_visual_review"
        assert candidate["reviewer_kind"] == "ai" and candidate["human_review_completed"] is False
        assert candidate["annotation_package"] == annotation_pin
        assert candidate["label_mask"] == refinements[sample_id]["artifacts"]["labels"]
        assert candidate["prior_mask_evidence"]["notes"] == row["notes"]
        assert candidate["prior_mask_evidence"]["method"] == row["method"]
        assert "retain historical observation" not in " ".join(candidate["notes"])
    assert review["before_atlas_outcomes"] is False
    assert review["before_candidate_registration"] is True
    assert review["human_review_completed"] is review["g3_complete"] is False


def test_review_never_silently_drops_an_unprepared_focus_target(tmp_path):
    original, refinements, annotation_pin, output, roles, plan_pin = review_fixture(tmp_path)
    refinements.pop("fgnet-004a63--sam-045")
    with pytest.raises((KeyError, ValueError)):
        probe._build_review(
            original, refinements, annotation_pin, output, tmp_path, roles, plan_pin
        )


@pytest.mark.parametrize("problem", ["wrong_output_path", "missing_label"])
def test_review_requires_three_exact_candidate_artifact_bindings(tmp_path, problem):
    original, refinements, annotation_pin, output, roles, plan_pin = review_fixture(tmp_path)
    artifacts = refinements[probe.FOCUS_IDS[0]]["artifacts"]
    if problem == "wrong_output_path":
        artifacts["allowed"]["path"] = "prior/old-allowed.png"
    else:
        artifacts.pop("labels")
    with pytest.raises(ValueError):
        probe._build_review(
            original, refinements, annotation_pin, output, tmp_path, roles, plan_pin
        )


def test_inherited_overlay_review_does_not_promote_new_candidate_visual_qa(tmp_path):
    original, refinements, annotation_pin, output, roles, plan_pin = review_fixture(tmp_path)
    original.update(
        mask_overlays_reviewed=True,
        mask_overlay_reviewed_before_atlas_outcomes=True,
        contact_sheets=[{"path": "prior/historical.png", "bytes": 1, "sha256": "a" * 64}],
    )
    before = copy.deepcopy(original)
    old_pin = {"path": "prior/old-review.json", "bytes": 1, "sha256": "a" * 64}
    review, _ = probe._build_review(
        original, refinements, annotation_pin, output, tmp_path, roles, plan_pin, old_pin
    )
    assert original == before
    assert review["mask_overlays_reviewed"] is False
    assert review["mask_overlay_reviewed_before_atlas_outcomes"] is False
    assert review["candidate_visual_qa_pending"] is True
    assert review["inherited_original_review_metadata"]["source"] == old_pin
    historical = review["inherited_original_review_metadata"]["metadata"]
    assert historical["mask_overlays_reviewed"] is True
    assert historical["mask_overlay_reviewed_before_atlas_outcomes"] is True
    assert historical["contact_sheets"] == before["contact_sheets"]
    assert "contact_sheets" not in review
    assert review["human_review_completed"] is review["g3_complete"] is False


@pytest.mark.parametrize(
    "problem", [None, "missing", "duplicate", "changed_control", "role_pin", "registered_target"]
)
def test_full37_review_gate_requires_every_exact_historical_row_and_role(tmp_path, problem):
    review, *_ = review_fixture(tmp_path)
    old_pin = {"path": "prior/original-review.json", "bytes": 1, "sha256": "a" * 64}
    registration_pin = {"path": "prior/registration.json", "bytes": 1, "sha256": "b" * 64}
    registration = {
        "inputs": {"mask_review": copy.deepcopy(old_pin)},
        "records": [
            {"sample_id": row["sample_id"], "mask_review": copy.deepcopy(row)}
            for row in review["target_records"]
        ],
    }
    metadata = {
        "original_review": review,
        "mask_report": {"roles": {"mask_review": old_pin, "registration_report": registration_pin}},
    }
    inputs = SimpleNamespace(read=lambda value, limit: json.dumps(registration).encode())
    if problem is None:
        assert probe._validate_original_review(inputs, metadata) == review
        return
    if problem == "missing":
        review["target_records"].pop()
    elif problem == "duplicate":
        review["target_records"][-1] = copy.deepcopy(review["target_records"][-2])
    elif problem == "changed_control":
        review["target_records"][-1]["notes"] = ["unbound changed control"]
    elif problem == "role_pin":
        registration["inputs"]["mask_review"]["sha256"] = "c" * 64
    else:
        registration["records"][-1]["sample_id"] = "foreign-registration-target"
    with pytest.raises(ValueError):
        probe._validate_original_review(inputs, metadata)


def annotation_bundle(annotation, review):
    rows = {row["sample_id"]: row for row in review["target_records"]}
    return {
        "schema_version": 1,
        "records": [
            {
                **copy.deepcopy(annotation),
                "sample_id": sample,
                "target_image": copy.deepcopy(rows[sample]["input"]),
            }
            for sample in probe.FOCUS_IDS
        ],
    }


@pytest.mark.parametrize("problem", [None, "missing", "duplicate", "foreign", "reassigned_image"])
def test_annotation_package_covers_exact_four_focus_images(tmp_path, annotation, problem):
    review, *_ = review_fixture(tmp_path)
    bundle = annotation_bundle(annotation, review)
    if problem is None:
        assert set(probe._validate_annotations(bundle, review)) == set(probe.FOCUS_IDS)
        return
    if problem == "missing":
        bundle["records"].pop()
    elif problem == "duplicate":
        bundle["records"][1] = copy.deepcopy(bundle["records"][0])
    elif problem == "foreign":
        bundle["records"][1]["sample_id"] = "different-focus-target"
    else:
        bundle["records"][0]["target_image"] = copy.deepcopy(bundle["records"][1]["target_image"])
    with pytest.raises(ValueError):
        probe._validate_annotations(bundle, review)


def test_input_closure_includes_all37_image_fit_masks_and_annotation_evidence(
    tmp_path, monkeypatch, annotation
):
    review, *_ = review_fixture(tmp_path)
    evidence = {"path": "prior/observation.json", "bytes": 1, "sha256": "e" * 64}
    bundle = annotation_bundle(annotation, review)
    bundle["evidence"] = evidence
    metadata = {"original_review": review, "annotations": bundle}
    monkeypatch.setattr(probe.workbench, "derive_input_pins", lambda metadata: [])
    pins = probe.derive_input_pins(metadata)
    assert len(pins) == 37 * 4 + 1
    assert {pin["path"] for pin in pins} == {
        row[key]["path"]
        for row in review["target_records"]
        for key in ("input", "target_fit", "allowed_mask", "occluded_mask")
    } | {evidence["path"]}
    bundle["evidence"] = {**review["target_records"][0]["input"], "sha256": "f" * 64}
    with pytest.raises(ValueError, match="Conflicting"):
        probe.derive_input_pins(metadata)


@pytest.mark.parametrize(
    "problem", ["age_default", "margin", "recipe", "results_seen", "human", "accepted"]
)
def test_protocol_rejects_age_defaults_recipe_drift_or_quality_promotion(problem):
    protocol = json.loads((_PATH.parent.parent / "docs/conservative-mask-v1.json").read_bytes())
    probe._protocol(protocol)
    if problem == "age_default":
        protocol["cohort"]["api_source_age"] = {
            "value": 50,
            "method": "default",
            "calibration_id": None,
        }
    elif problem == "margin":
        protocol["rasterization"]["margin_pixels"] = 11
    elif problem == "recipe":
        protocol["refinement"]["release"] = "all_old_occluded"
    elif problem == "results_seen":
        protocol["observations"]["candidate_mask_results_seen_before_freeze"] = True
    elif problem == "human":
        protocol["flags"]["human_review_completed"] = True
    else:
        protocol["flags"]["usable_mask_candidate_accepted"] = True
    with pytest.raises(ValueError):
        probe._protocol(protocol)


@pytest.fixture
def synthetic_run(tmp_path, monkeypatch, annotation, old_masks, layers):
    (tmp_path / ".gitignore").write_text("output/\n", encoding="utf-8")
    runtime = {"synthetic_runtime": True}

    def frozen(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else json.dumps(value, allow_nan=False).encode()
        path.write_bytes(raw)
        return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    source_pins = [frozen(name, b"# synthetic source snapshot\n") for name in probe.SOURCES]
    monkeypatch.setattr(
        probe,
        "_LOADED_SOURCE_HASHES",
        {
            value["path"]: value["sha256"]
            for value in source_pins
            if value["path"] in probe._LOADED_SOURCE_HASHES
        },
    )
    fixture_pin = frozen("prior/fixture.json", {"synthetic": True})
    original_review, *_ = review_fixture(tmp_path)
    for row in original_review["target_records"]:
        if row["sample_id"] in probe.FOCUS_IDS:
            row["input"] = fixture_pin
    old_review_pin = frozen("prior/original-review.json", original_review)
    bundle = annotation_bundle(annotation, original_review)
    primary, selected, old_records = [], [], {}
    for source, ages in probe.uv.COHORT.items():
        for age in ages:
            sample_id = f"{source}--sam-{age:03d}"
            selected.append(
                {
                    "registration": {
                        "sample_id": sample_id,
                        "source_id": source,
                        "target_age": age,
                        "source_age_label": {
                            "fgnet-004a63": 63,
                            "fgnet-082a27": 27,
                            "fgnet-006a55": 55,
                        }[source],
                        "input": fixture_pin,
                        "target_fit": fixture_pin,
                        "source_frame": {"synthetic": True},
                    }
                }
            )
            primary.append(
                {
                    "sample_id": sample_id,
                    "pixel_comparison": {"exact": True},
                    "layer_pixel_counts": {"synthetic": True},
                    "decomposition": {"synthetic": True},
                }
            )
            old_records[sample_id] = {"correspondence": fixture_pin}
    protocol = json.loads((_PATH.parent.parent / "docs/conservative-mask-v1.json").read_bytes())
    roles = {
        "protocol": frozen("prior/protocol.json", protocol),
        "mask_report": frozen(
            "prior/report.json", {"roles": {"mask_review": old_review_pin}, "records": primary}
        ),
        "mask_audit": frozen("prior/audit.json", {"synthetic": True}),
        "uv_report": frozen("prior/uv.json", {"synthetic": True}),
        "annotations": frozen("prior/annotations.json", bundle),
    }
    plan = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "runtime": runtime,
        "roles": roles,
        "inputs": [*source_pins, old_review_pin, fixture_pin, *roles.values()],
    }
    plan_path = tmp_path / "study-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(probe.uv, "runtime_fingerprint", lambda: runtime)
    monkeypatch.setattr(probe, "derive_input_pins", lambda metadata: [])
    monkeypatch.setattr(probe.workbench, "validate_evidence", lambda *args: (selected, old_records))
    monkeypatch.setattr(probe, "_validate_original_review", lambda *args: original_review)
    monkeypatch.setattr(
        probe, "_validate_annotations", lambda *args: {a["sample_id"]: a for a in bundle["records"]}
    )
    baseline_calls, prepare_calls = [], []

    def baseline(inputs, item, old, saved):
        baseline_calls.append(item["registration"]["sample_id"])
        return ({"synthetic": True}, np.zeros((256, 256), np.uint8), {})

    def prepare(inputs, item, annot, annotation_pin):
        sample = item["registration"]["sample_id"]
        prepare_calls.append(sample)
        refined = probe.refine_masks(*old_masks, layers)
        payloads = {
            f"masks/{sample}-{role}.png": probe._png(
                refined[role] if role == "labels" else refined[role].astype(np.uint8) * 255
            )
            for role in ("allowed", "occluded", "labels")
        }
        return refined, payloads

    monkeypatch.setattr(probe, "_baseline_record", baseline)
    monkeypatch.setattr(probe, "_prepare_refinement", prepare)
    return SimpleNamespace(
        args=SimpleNamespace(
            root=tmp_path,
            study_plan=plan_path,
            output_dir=tmp_path / "output/research/conservative",
        ),
        plan=plan,
        baseline_calls=baseline_calls,
        prepare_calls=prepare_calls,
        baseline=baseline,
        prepare=prepare,
        source_path=tmp_path / "tools/conservative_mask_probe.py",
    )


def test_run_checks_all12_baselines_before_preparing_only_four_focus_candidates(
    synthetic_run, monkeypatch
):
    def prepare(*args):
        assert len(synthetic_run.baseline_calls) == 12
        return synthetic_run.prepare(*args)

    monkeypatch.setattr(probe, "_prepare_refinement", prepare)
    report = probe.run(synthetic_run.args)
    assert len(synthetic_run.baseline_calls) == 12 and set(synthetic_run.prepare_calls) == set(
        probe.FOCUS_IDS
    )
    assert report["summary"]["all_requested_verified"] is True
    assert (
        report["summary"]["candidate_targets"] == 4
        and report["summary"]["unchanged_review_rows"] == 33
    )
    assert all(
        row["source_age"] == {"value": None, "method": "unknown", "calibration_id": None}
        for row in report["records"]
    )
    assert (
        report["human_review_completed"]
        is report["g3_complete"]
        is report["usable_mask_candidate_accepted"]
        is False
    )
    assert len(list(synthetic_run.args.output_dir.rglob("*.png"))) == 12


def test_one_failed_baseline_prevents_every_refinement_and_preserves_twelve_requests(
    synthetic_run, monkeypatch
):
    def baseline(inputs, item, old, saved):
        if item["registration"]["sample_id"].endswith("--sam-063"):
            raise ValueError("synthetic old-mask mismatch")
        return synthetic_run.baseline(inputs, item, old, saved)

    monkeypatch.setattr(probe, "_baseline_record", baseline)
    monkeypatch.setattr(
        probe, "_prepare_refinement", lambda *args: pytest.fail("baseline gate bypassed")
    )
    report = probe.run(synthetic_run.args)
    assert len(report["records"]) == 12 and report["summary"]["all_baselines_verified"] is False
    assert report["summary"]["candidate_targets"] == 0 and report["artifacts"] == {}
    assert all(row["refinement"] is None and row["artifacts"] == {} for row in report["records"])
    assert not list(synthetic_run.args.output_dir.rglob("*.png"))


def test_one_failed_focus_preparation_withholds_every_candidate_file(synthetic_run, monkeypatch):
    def prepare(inputs, item, annotation, annotation_pin):
        if item["registration"]["sample_id"].endswith("--sam-045"):
            raise ValueError("synthetic protected-region preparation failure")
        return synthetic_run.prepare(inputs, item, annotation, annotation_pin)

    monkeypatch.setattr(probe, "_prepare_refinement", prepare)
    report = probe.run(synthetic_run.args)
    assert len(report["records"]) == 12 and report["summary"]["all_baselines_verified"] is True
    assert report["summary"]["all_requested_verified"] is False
    assert report["summary"]["candidate_targets"] == 0
    assert not list(synthetic_run.args.output_dir.rglob("*.png"))
    assert not (synthetic_run.args.output_dir / "mask-review.json").exists()


@pytest.mark.parametrize("kind", ["source", "plan", "runtime"])
def test_late_source_plan_or_runtime_drift_removes_all_prepared_candidate_files(
    synthetic_run, monkeypatch, kind
):
    changed = False

    def prepare(*args):
        nonlocal changed
        result = synthetic_run.prepare(*args)
        if not changed:
            if kind == "source":
                synthetic_run.source_path.write_bytes(b"changed after original input snapshot")
            elif kind == "plan":
                synthetic_run.args.study_plan.write_text(
                    json.dumps({**synthetic_run.plan, "late_change": True}), encoding="utf-8"
                )
            else:
                monkeypatch.setattr(probe.uv, "runtime_fingerprint", lambda: {"runtime": "changed"})
            changed = True
        return result

    monkeypatch.setattr(probe, "_prepare_refinement", prepare)
    report = probe.run(synthetic_run.args)
    assert len(report["records"]) == 12
    assert report["candidate_files_created"] is False
    assert report["summary"]["candidate_targets"] == report["summary"]["unchanged_review_rows"] == 0
    assert all(
        row["status"] == "invalidated_input_drift"
        and row["artifacts"] == {}
        and row["refinement"] is None
        and "baseline" not in row
        for row in report["records"]
    )
    assert not list(synthetic_run.args.output_dir.rglob("*.png"))
    assert not (synthetic_run.args.output_dir / "mask-review.json").exists()


def test_loaded_source_mismatch_is_rejected_before_decoding_baseline(synthetic_run, monkeypatch):
    monkeypatch.setattr(
        probe, "_LOADED_SOURCE_HASHES", {"tools/conservative_mask_probe.py": "0" * 64}
    )
    with pytest.raises(ValueError, match="Loaded Python implementation"):
        probe.run(synthetic_run.args)
    assert not synthetic_run.baseline_calls and not synthetic_run.prepare_calls
    assert not synthetic_run.args.output_dir.exists()
