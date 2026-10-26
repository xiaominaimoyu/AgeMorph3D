"""Synthetic extension, exact lineage and all-or-nothing publication checks."""

import copy
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "observed_skin_candidate_probe", _ROOT / "tools/observed_skin_candidate_probe.py"
)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def pin(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": name, "bytes": len(data), "sha256": probe.uv._digest(data)}


@pytest.fixture
def annotation():
    return {
        "skin_polygons": [[[4, 4], [24, 4], [24, 24], [4, 24]]],
        "protected_polygons": [[[45, 45], [48, 45], [48, 48], [45, 48]]],
    }


def test_extension_releases_observed_pixels_outside_both_old_masks_and_retains_old_pixels(
    annotation,
):
    allowed = np.zeros((64, 64), bool)
    allowed[0, 0] = True
    excluded = np.zeros_like(allowed)
    excluded[10:15, 10:15] = True
    before = allowed.copy(), excluded.copy()
    result = probe.extend_masks(allowed, excluded, probe.rasterize(annotation, 64, 64))
    assert result["counts"]["newly_allowed_pixels"] == 441
    assert result["counts"]["newly_allowed_outside_old_occluded_pixels"] == 441 - 25
    assert result["counts"]["new_allowed_pixels"] == 442
    assert result["counts"]["new_occluded_pixels"] == 0
    assert result["allowed"][4, 4] and result["allowed"][24, 24]
    assert not result["allowed"][3, 4] and not result["allowed"][25, 24]
    assert result["allowed"][0, 0] and not result["occluded"].any()
    assert np.array_equal(allowed, before[0]) and np.array_equal(excluded, before[1])


def test_new_skin_respects_protection_while_inherited_allowed_can_overlap_protection(annotation):
    annotation["skin_polygons"] = [[[0, 0], [63, 0], [63, 63], [0, 63]]]
    allowed = np.zeros((64, 64), bool)
    allowed[45, 45] = True
    excluded = np.zeros_like(allowed)
    excluded[40, 40] = True
    layers = probe.rasterize(annotation, 64, 64)
    result = probe.extend_masks(allowed, excluded, layers)
    assert layers["protected_margin"].sum() == 28 * 28
    assert result["counts"]["inherited_allowed_protected_pixels"] == 1
    assert result["counts"]["newly_allowed_protected_pixels"] == 0
    assert result["allowed"][45, 45] and result["occluded"][40, 40]
    assert result["labels"][45, 45] == 2
    assert result["labels"][40, 40] == 2
    assert not np.any(result["allowed"] & result["occluded"])


def test_raster_union_has_no_overlap_holes_and_winding_is_invariant(annotation):
    annotation["skin_polygons"] = [
        [[1, 1], [10, 1], [10, 10], [1, 10]],
        [[6, 6], [15, 6], [15, 15], [6, 15]],
    ]
    result = probe.rasterize(annotation, 64, 64)
    assert result["skin"].sum() == 2 * 100 - 25
    reverse = copy.deepcopy(annotation)
    reverse["skin_polygons"] = [points[::-1] for points in reverse["skin_polygons"]]
    for name, pixels in result.items():
        assert np.array_equal(pixels, probe.rasterize(reverse, 64, 64)[name])


@pytest.mark.parametrize(
    "polygon",
    [
        [[1, 1], [5, 1], [5, 5], [1, 1]],
        [[1, 1], [5, 5], [1, 5], [5, 1]],
        [[1, 1], [2, 2], [3, 3]],
        [[1, 1], [5.0, 1], [5, 5]],
        [[1, 1], [64, 1], [5, 5]],
        [[1, 1], [True, 3], [5, 5]],
    ],
)
def test_invalid_native_polygons_are_rejected(annotation, polygon):
    annotation["skin_polygons"] = [polygon]
    with pytest.raises(ValueError):
        probe.rasterize(annotation, 64, 64)


def test_tampered_dilation_or_nonboolean_layers_are_rejected(annotation):
    old = np.zeros((64, 64), bool)
    layers = probe.rasterize(annotation, 64, 64)
    layers["protected_margin"][0, 0] = True
    with pytest.raises(ValueError, match="frame/margin"):
        probe.extend_masks(old, old, layers)
    layers = probe.rasterize(annotation, 64, 64)
    layers["skin"] = layers["skin"].astype(np.uint8)
    with pytest.raises(ValueError, match="frame/margin"):
        probe.extend_masks(old, old, layers)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path
    (root / ".gitignore").write_text("output/\n", encoding="utf-8")
    for name in probe.SOURCES:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_ROOT / name, destination)
    runtime = {"synthetic_test_runtime": True}
    monkeypatch.setattr(probe, "runtime_fingerprint", lambda: copy.deepcopy(runtime))
    protocol = json.loads((_ROOT / "docs/observed-skin-candidate-v1.json").read_bytes())
    rgb = probe.prior._png(np.full((1024, 1024, 3), 100, np.uint8))
    old_allowed = np.zeros((1024, 1024), np.uint8)
    old_allowed[100, 100] = 255
    old_occluded = np.zeros_like(old_allowed)
    old_occluded[20:30, 20:30] = 255
    allowed_png, occluded_png = [probe.prior._png(a) for a in (old_allowed, old_occluded)]
    rows, annotations, old_annotations = [], [], []
    protection = [[[700, 700], [720, 700], [720, 720], [700, 720]]]
    for sample in probe.FOCUS_IDS:
        pins = {
            "input": pin(root, f"prior/{sample}.png", rgb),
            "target_fit": pin(root, f"prior/{sample}.npz", b"synthetic pinned fit; never decoded"),
            "allowed_mask": pin(root, f"prior/{sample}-allowed.png", allowed_png),
            "occluded_mask": pin(root, f"prior/{sample}-occluded.png", occluded_png),
        }
        rows.append(
            {
                "sample_id": sample,
                **pins,
                "allowed_pixels": 1,
                "excluded_occluder_pixels": 100,
                "method": "historical-method",
                "notes": ["historical-notes"],
                "exclusions": [{"kind": "historical"}],
                "label_mask": {"stale": True},
                "refinement_counts": {"stale": True},
                "prior_mask_evidence": {"stale": True},
            }
        )
        annotations.append(
            {
                "sample_id": sample,
                "input": pins["input"],
                "target_fit": pins["target_fit"],
                "source_age_api": copy.deepcopy(probe.uv.UNKNOWN_AGE),
                "reviewer_kind": "ai",
                "reviewer": "codex-root-native-target-observation",
                "skin_polygons": [[[10, 10], [40, 10], [40, 40], [10, 40]]],
                "protected_polygons": copy.deepcopy(protection),
            }
        )
        old_annotations.append(
            {
                "sample_id": sample,
                "target_image": pins["input"],
                "margin_pixels": 12,
                "protected_polygons": copy.deepcopy(protection),
            }
        )
    rows.extend(
        {"sample_id": f"inherited-{index}", "arbitrary_original_data": [index, {"v": None}]}
        for index in range(33)
    )
    metadata = {
        "protocol": protocol,
        "parent_review": {
            "schema_version": 1,
            "protocol_id": "agemorph3d-target-uv-v1",
            "candidate_protocol_id": probe.prior.PROTOCOL_ID,
            "target_records": rows,
            "mask_overlays_reviewed": True,
        },
        "annotations": {
            "schema_version": 1,
            "protocol_id": probe.ANNOTATION_ID,
            "reviewer_kind": "ai",
            "human_review_completed": False,
            "before_new_mask_and_atlas": True,
            "historical_results_seen": True,
            "records": annotations,
        },
        "parent_annotations": {
            "schema_version": 1,
            "protocol_id": "agemorph3d-conservative-mask-annotations-v1",
            "records": old_annotations,
        },
    }
    paths = {
        "protocol": "docs/observed-skin-candidate-v1.json",
        "parent_review": protocol["cohort"]["parent_review"],
        "annotations": "study/annotations.json",
        "parent_annotations": "study/parent-annotations.json",
    }
    parent_annotation_pin = pin(
        root, paths["parent_annotations"], probe._encode(metadata["parent_annotations"])
    )
    metadata["parent_review"]["annotation_package"] = parent_annotation_pin
    for row in metadata["parent_review"]["target_records"][:4]:
        row["annotation_package"] = parent_annotation_pin
    roles = {name: pin(root, paths[name], probe._encode(value)) for name, value in metadata.items()}
    all_pins = [*roles.values(), *probe.derive_input_pins(metadata)]
    for name in probe.SOURCES:
        all_pins.append(pin(root, name, (root / name).read_bytes()))
    plan = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "roles": roles,
        "inputs": all_pins,
        "runtime": runtime,
    }
    plan_path = root / "study/plan.json"
    plan_path.write_bytes(probe._encode(plan))
    args = SimpleNamespace(root=root, study_plan=plan_path, output_dir="output/research/candidate")
    return args, plan, metadata


def save_plan(args, plan):
    args.study_plan.write_bytes(probe._encode(plan))


def test_frozen_batch_preserves_other33_and_isolates_stale_history(frozen):
    args, _, metadata = frozen
    original = copy.deepcopy(metadata["parent_review"])
    report = probe.run(args)
    output = args.root / args.output_dir
    review = json.loads((output / "mask-review.json").read_bytes())
    assert review["target_records"][4:] == original["target_records"][4:]
    assert review["candidate_visual_qa_pending"] is True
    assert review["mask_overlays_reviewed"] is False
    assert review["inherited_parent_metadata"]["mask_overlays_reviewed"] is True
    for row, before in zip(
        review["target_records"][:4], original["target_records"][:4], strict=True
    ):
        assert row["inherited_parent_review"] == before
        assert "refinement_counts" not in row and "prior_mask_evidence" not in row
        assert row["label_mask"] != before["label_mask"]
        assert row["allowed_pixels"] == 962 and row["excluded_occluder_pixels"] == 0
    assert report["summary"] == {
        "requested_targets": 4,
        "statuses": {"ok": 4},
        "published_mask_sets": 4,
        "unchanged_review_rows": 33,
        "full_review_targets": 37,
        "all_requested_verified": True,
    }
    assert all(report[name] is False for name in probe.FALSE_FLAGS)
    assert len(list(output.rglob("*.png"))) == 28
    assert metadata["parent_review"] == original


@pytest.mark.parametrize("mutation", ["extra_input", "hash", "runtime", "source", "role_path"])
def test_closed_freeze_rejects_unrelated_input_hash_runtime_source_or_lineage_drift(
    frozen, mutation
):
    args, plan, _ = frozen
    if mutation == "extra_input":
        plan["inputs"].append(pin(args.root, "study/unrelated.json", b"{}"))
    elif mutation == "hash":
        input_pin = next(p for p in plan["inputs"] if p["path"].endswith("-allowed.png"))
        (args.root / input_pin["path"]).write_bytes(b"tampered")
    elif mutation == "runtime":
        plan["runtime"] = {"unexpected": True}
    elif mutation == "source":
        source = next(
            p for p in plan["inputs"] if p["path"] == "tools/observed_skin_candidate_probe.py"
        )
        source["sha256"] = "0" * 64
    else:
        plan["roles"]["parent_review"] = dict(
            plan["roles"]["parent_review"], path="study/reassigned.json"
        )
    save_plan(args, plan)
    with pytest.raises(ValueError):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


@pytest.mark.parametrize("mutation", ["plan", "source", "runtime"])
def test_drift_after_calculation_rolls_back_the_whole_candidate(frozen, monkeypatch, mutation):
    args, _, _ = frozen
    original_extend = probe.extend_masks
    changed = False

    def extend_then_drift(*values):
        nonlocal changed
        result = original_extend(*values)
        if not changed:
            changed = True
            if mutation == "plan":
                args.study_plan.write_bytes(args.study_plan.read_bytes() + b"\n")
            elif mutation == "source":
                path = args.root / "tools/observed_skin_candidate_probe.py"
                path.write_bytes(path.read_bytes() + b"\n# synthetic drift\n")
            else:
                monkeypatch.setattr(probe, "runtime_fingerprint", lambda: {"changed": True})
        return result

    monkeypatch.setattr(probe, "extend_masks", extend_then_drift)
    with pytest.raises(ValueError, match="drift"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()
    assert not list((args.root / "output/research").glob("candidate.preparing-*"))


@pytest.mark.parametrize("mutation", ["protect", "fit", "age", "human", "missing", "duplicate"])
def test_annotations_reject_reassigned_assets_protection_age_or_approval(frozen, mutation):
    _, _, metadata = frozen
    annotation = metadata["annotations"]["records"][0]
    if mutation == "protect":
        annotation["protected_polygons"][0][0][0] -= 1
    elif mutation == "fit":
        annotation["target_fit"] = dict(annotation["target_fit"], sha256="0" * 64)
    elif mutation == "age":
        annotation["source_age_api"]["value"] = 63
    elif mutation == "human":
        metadata["annotations"]["human_review_completed"] = True
    elif mutation == "missing":
        metadata["annotations"]["records"].pop()
    else:
        metadata["annotations"]["records"].append(copy.deepcopy(annotation))
    with pytest.raises(ValueError):
        probe.validate_annotations(metadata)


@pytest.mark.parametrize("audit_failure", [1, 2, 3])
def test_audit_failure_at_each_publication_stage_leaves_no_partial_success(tmp_path, audit_failure):
    output = tmp_path / "candidate"
    calls = 0

    def audit():
        nonlocal calls
        calls += 1
        if calls == audit_failure:
            raise ValueError("synthetic drift")

    with pytest.raises(ValueError, match="synthetic drift"):
        probe.publish_batch(output, {"report.json": b"{}", "masks/a.png": b"png"}, audit)
    assert not output.exists()
    assert not list(tmp_path.iterdir())


def test_existing_output_and_escaping_artifacts_are_never_overwritten(tmp_path):
    output = tmp_path / "candidate"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh output"):
        probe.publish_batch(output, {"report.json": b"{}"}, lambda: None)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    with pytest.raises(ValueError):
        probe.publish_batch(tmp_path / "fresh", {"../escape": b"x"}, lambda: None)
    assert not (tmp_path / "escape").exists()


def test_reads_and_rechecks_use_declared_plus_one_not_the_larger_resource_cap(
    tmp_path, monkeypatch
):
    item = pin(tmp_path, "small.dat", b"12345")
    inputs = probe.Inputs(tmp_path, [item])
    bounded = probe._bounded
    counts = []

    def observed(path, count):
        counts.append(count)
        return bounded(path, count)

    monkeypatch.setattr(probe, "_bounded", observed)
    assert inputs.read(item, 1000000) == b"12345"
    inputs.recheck()
    assert counts == [5, 5]
    (tmp_path / "small.dat").write_bytes(b"123456" * 1000)
    with pytest.raises(ValueError, match="drift"):
        inputs.recheck()


def test_duplicate_json_keys_nonfinite_metadata_and_path_escape_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        probe._json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError, match="Non-finite"):
        probe._json(b'{"a":NaN}')
    with pytest.raises(ValueError, match="escapes"):
        probe.Inputs(tmp_path, [{"path": "../outside", "bytes": 1, "sha256": "a" * 64}])


@pytest.mark.parametrize("number", [b"1e999", b"-1e999"])
def test_nested_json_exponent_overflow_is_rejected_instead_of_accepting_infinity(number):
    with pytest.raises(ValueError, match="exponent overflow"):
        probe._json(b'{"outer":[{"nested":' + number + b"}]}")
