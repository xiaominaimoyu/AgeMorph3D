"""Synthetic counterfactual sensitivity boundaries, without images or inference."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools/mask_candidate_probe.py"
_SPEC = importlib.util.spec_from_file_location("mask_candidate_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def make_candidate(*, band=True, border=False):
    points = np.full((68, 2), 32.0, dtype=np.float64)
    points[:4] = (
        [[0, 0], [63, 0], [63, 63], [0, 63]] if border else [[8, 8], [55, 8], [55, 55], [8, 55]]
    )
    points[60:68] = [[28, 28], [35, 28], [35, 35], [28, 35]] * 2
    exclusions = (
        [
            {
                "kind": "glasses_candidate_band",
                "x0": 0,
                "x1_exclusive": 64,
                "y0": 25,
                "y1_exclusive": 45,
            }
        ]
        if band
        else []
    )
    return probe.mask.construct_masks(points, 64, 64, exclusions)


def make_vectors(xy, classes, *, regions=None, candidate=None):
    """Choose UV addresses independently of XY and copy known old partition labels."""
    n = len(xy)
    rc = np.column_stack((np.zeros(n, dtype=np.int32), np.arange(n, dtype=np.int32)))
    grid = np.zeros((256, 256), dtype=np.uint8)
    grid[rc[:, 0], rc[:, 1]] = np.array(classes, dtype=np.uint8)
    grid[255, 255] = 1
    vectors = {
        "texel_rows_columns": rc,
        "face_owner": np.arange(n, dtype=np.int32),
        "barycentric": np.tile([0.25, 0.25, 0.5], (n, 1)),
        "target_xyz": np.column_stack(
            (np.asarray(xy, dtype=np.float64), np.arange(n, dtype=np.float64))
        ),
        "source_canonical_xyz": np.column_stack(
            (np.arange(n), -np.arange(n), np.arange(n) / 7)
        ).astype(np.float64),
        "region_bits": np.zeros(n, dtype=np.uint8)
        if regions is None
        else np.array(regions, dtype=np.uint8),
        "rejection_partition": np.zeros(n, dtype=np.uint8),
    }
    if candidate is not None:
        visible = np.asarray(classes) >= 5
        vectors["rejection_partition"][visible] = probe.uv.mask_rejection_partition(
            candidate["allowed"], candidate["occluded"], vectors["target_xyz"][visible, :2]
        )
    return grid, vectors


@pytest.fixture
def scenario():
    candidate = make_candidate()
    # B-only, B+erosion, already allowed, three geometric failures, mouth, erosion.
    grid, vectors = make_vectors(
        [[20, 30], [11.5, 30], [20, 20], [-3, 20], [-3, 20], [20, 30], [30, 30], [20, 8]],
        [5, 5, 6, 2, 3, 4, 5, 5],
        regions=[3, 5, 1, 8, 0, 2, 4, 15],
        candidate=candidate,
    )
    return candidate, grid, vectors


def test_only_band_only_support_is_released_with_exact_global_transition_counts(scenario):
    result = probe.evaluate_counterfactual(*scenario)
    assert result["released_texels"] == 1
    assert result["retained_mask_rejected_texels"] == 3
    matrix = np.asarray(result["classification_transition_7x7"])
    assert matrix.shape == (7, 7) and matrix.sum() == 65536
    assert matrix[0, 0] == 65527 and matrix[1, 1] == 1
    assert all(matrix[k, k] == 1 for k in (2, 3, 4, 6))
    assert matrix[5, 5] == 3 and matrix[5, 6] == 1
    assert np.count_nonzero(matrix - np.diag(np.diag(matrix))) == 1
    assert all(result["checks"].values())
    assert result["mask_delta"] == {
        "allowed": {"added_pixels": 604, "removed_pixels": 0, "unchanged_pixels": 3492},
        "occluded": {"added_pixels": 0, "removed_pixels": 604, "unchanged_pixels": 3492},
    }


def test_overlapping_regions_preserve_original_unique_correspondence_denominators(scenario):
    result = probe.evaluate_counterfactual(*scenario)
    before = result["arms"]["old_baseline"]["counts"]
    after = result["arms"]["remove_B_upper_bound"]["counts"]
    expected_denominators = dict(
        zip(("all_unique_correspondence", *probe.uv.REGIONS), [8, 4, 3, 3, 2], strict=True)
    )
    for name, requested in expected_denominators.items():
        assert before[name]["requested"] == after[name]["requested"] == requested
        assert sum(before[name]["classification_counts"].values()) == requested
        assert sum(after[name]["classification_counts"].values()) == requested
        change = result["regional_changes"][name]
        matrix = np.asarray(change["classification_transition_7x7"])
        assert matrix.shape == (7, 7) and matrix.sum() == requested
        assert matrix[:2].sum() == matrix[:, :2].sum() == 0
        assert change["released_texels"] == matrix[5, 6]
        for label, code in probe.uv.REASONS.items():
            assert matrix[code].sum() == before[name]["classification_counts"][label]
            assert matrix[:, code].sum() == after[name]["classification_counts"][label]
    assert before["all_unique_correspondence"]["rejection_counts"] == {
        "reviewed_occluder_only": 1,
        "other_ineligible_only": 2,
        "mixed_contributors": 1,
    }
    assert after["all_unique_correspondence"]["rejection_counts"] == {
        "reviewed_occluder_only": 0,
        "other_ineligible_only": 3,
        "mixed_contributors": 0,
    }
    assert after["eye_36_41"]["classification_counts"]["sampled"] == 2
    assert after["eye_42_47"]["classification_counts"]["sampled"] == 1
    assert after["nose_27_35"]["classification_counts"]["sampled"] == 0


def test_counterfactual_never_mutates_geometry_uv_addresses_or_original_masks(scenario):
    before = copy.deepcopy(scenario)
    result = probe.evaluate_counterfactual(*scenario)
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    for name, original in before[0].items():
        if isinstance(original, np.ndarray):
            np.testing.assert_array_equal(scenario[0][name], original)
        else:
            assert scenario[0][name] == original
    np.testing.assert_array_equal(scenario[1], before[1])
    for name, original in before[2].items():
        assert scenario[2][name].dtype == original.dtype
        assert scenario[2][name].tobytes() == original.tobytes()


def test_zero_weight_neighbor_is_ignored_but_every_positive_weight_keeps_other_rejection():
    candidate = make_candidate()
    grid, vectors = make_vectors(
        [[12, 30], [np.nextafter(12.0, -np.inf), 30]], [5, 5], candidate=candidate
    )
    np.testing.assert_array_equal(vectors["rejection_partition"], [1, 3])
    result = probe.evaluate_counterfactual(candidate, grid, vectors)
    assert result["released_texels"] == 1 and result["retained_mask_rejected_texels"] == 1


def test_exact_final_image_pixel_is_legal_without_inventing_an_extra_neighbor():
    candidate = make_candidate(border=True)
    grid, vectors = make_vectors([[63, 30], [63, 63]], [5, 6], candidate=candidate)
    result = probe.evaluate_counterfactual(candidate, grid, vectors)
    assert result["released_texels"] == 1
    assert result["retained_mask_rejected_texels"] == 0


def test_no_band_control_is_identical_in_both_arms_and_never_gains_support():
    candidate = make_candidate(band=False)
    grid, vectors = make_vectors([[20, 30], [11.5, 30], [-100, 30]], [6, 5, 3], candidate=candidate)
    result = probe.evaluate_counterfactual(candidate, grid, vectors)
    assert result["released_texels"] == 0
    assert result["arms"]["old_baseline"] == result["arms"]["remove_B_upper_bound"]
    assert result["mask_delta"]["allowed"]["added_pixels"] == 0
    assert result["mask_delta"]["occluded"]["removed_pixels"] == 0
    matrix = np.asarray(result["classification_transition_7x7"])
    assert not (matrix - np.diag(np.diag(matrix))).any()


def test_empty_unique_uv_domain_keeps_undefined_region_support_null():
    candidate = make_candidate()
    grid, vectors = make_vectors(np.empty((0, 2)), [], candidate=candidate)
    result = probe.evaluate_counterfactual(candidate, grid, vectors)
    assert result["released_texels"] == result["retained_mask_rejected_texels"] == 0
    for arm in result["arms"].values():
        assert all(v["requested"] == 0 and v["support"] is None for v in arm["counts"].values())


@pytest.mark.parametrize(
    "problem", ["shape", "dtype", "unknown_code", "missing_owner", "ambiguous_owner"]
)
def test_classification_cannot_change_frame_or_unique_coverage(scenario, problem):
    candidate, grid, vectors = scenario
    if problem == "shape":
        grid = grid[:255]
    elif problem == "dtype":
        grid = grid.astype(np.int64)
    elif problem == "unknown_code":
        grid[100, 100] = 7
    elif problem == "missing_owner":
        grid[100, 100] = 5
    else:
        grid[0, 0] = 1
    with pytest.raises(ValueError):
        probe.evaluate_counterfactual(candidate, grid, vectors)


@pytest.mark.parametrize(
    "problem",
    [
        "allowed_overlap",
        "base_union",
        "eroded_outside_hull",
        "reason",
        "counts",
        "reason_counts",
        "nonbool",
        "shape",
    ],
)
def test_candidate_must_retain_the_complete_validated_old_recipe(scenario, problem):
    candidate, grid, vectors = scenario
    if problem == "allowed_overlap":
        candidate["allowed"][30, 20] = True
    elif problem == "base_union":
        candidate["base"][0, 0] = True
    elif problem == "eroded_outside_hull":
        candidate["E"][0, 0] = True
    elif problem == "reason":
        candidate["reason"][30, 20] = 0
    elif problem == "counts":
        candidate["pixel_counts"]["allowed"] += 1
    elif problem == "reason_counts":
        candidate["pixel_counts"]["reasons"]["reviewed_candidate_band"] += 1
    elif problem == "nonbool":
        candidate["base"] = candidate["base"].astype(np.uint8)
    else:
        candidate["B"] = candidate["B"][:63]
    with pytest.raises(ValueError):
        probe.evaluate_counterfactual(candidate, grid, vectors)


@pytest.mark.parametrize(
    "problem",
    [
        "nan_target",
        "nan_canonical",
        "float32",
        "missing",
        "duplicate_rc",
        "reversed_rc",
        "negative_rc",
        "bad_bary",
        "unknown_region",
        "bad_partition",
    ],
)
def test_correspondence_contract_rejects_invalid_vectors_without_repair(scenario, problem):
    candidate, grid, vectors = scenario
    if problem == "nan_target":
        vectors["target_xyz"][3, 0] = np.nan
    elif problem == "nan_canonical":
        vectors["source_canonical_xyz"][3, 0] = np.nan
    elif problem == "float32":
        vectors["barycentric"] = vectors["barycentric"].astype(np.float32)
    elif problem == "missing":
        vectors.pop("face_owner")
    elif problem == "duplicate_rc":
        vectors["texel_rows_columns"][1] = vectors["texel_rows_columns"][0]
    elif problem == "reversed_rc":
        vectors["texel_rows_columns"] = vectors["texel_rows_columns"][::-1].copy()
    elif problem == "negative_rc":
        vectors["texel_rows_columns"][0, 0] = -1
    elif problem == "bad_bary":
        vectors["barycentric"][0] = [0.5, 0.5, 0.5]
    elif problem == "unknown_region":
        vectors["region_bits"][0] = 16
    else:
        vectors["rejection_partition"][0] = 4
    with pytest.raises(ValueError):
        probe.evaluate_counterfactual(candidate, grid, vectors)


@pytest.mark.parametrize(
    "problem",
    [
        "false_allowed",
        "false_rejected",
        "wrong_partition",
        "geometric_partition",
        "out_of_image_visible",
    ],
)
def test_baseline_classes_and_partitions_cannot_be_relabelled_to_inflate_release(scenario, problem):
    candidate, grid, vectors = scenario
    if problem == "false_allowed":
        grid[0, 0] = 6
    elif problem == "false_rejected":
        grid[0, 2] = 5
    elif problem == "wrong_partition":
        vectors["rejection_partition"][0] = 2
    elif problem == "geometric_partition":
        vectors["rejection_partition"][3] = 1
    else:
        vectors["target_xyz"][0, 0] = -0.001
    with pytest.raises(ValueError):
        probe.evaluate_counterfactual(candidate, grid, vectors)


def publication_fixture():
    records = [
        {
            "sample_id": f"{source}--sam-{age:03d}",
            "status": "ok",
            "baseline": {"synthetic": True},
            "sensitivity": {"released_texels": 1},
        }
        for source, ages in probe.uv.COHORT.items()
        for age in ages
    ]
    return {
        "inputs": [],
        "records": records,
        "summary": {
            "requested_targets": 12,
            "requested_sources": 3,
            "baseline_targets": 12,
            "all_baselines_verified": True,
            "candidate_targets": 12,
            "all_requested_verified": True,
            "statuses": {"ok": 12},
        },
    }


@pytest.mark.parametrize("fail_on", [1, 2])
def test_each_publication_drift_phase_clears_all_candidate_and_baseline_values(tmp_path, fail_on):
    report = publication_fixture()
    output = tmp_path / "new-report"
    calls = 0

    def audit():
        nonlocal calls
        calls += 1
        if calls == fail_on:
            (output / "foreign-note.txt").write_bytes(b"keep foreign file")
            raise ValueError("synthetic source/plan/runtime drift")

    result = probe.publish_report(output, report, audit)
    assert len(result["records"]) == 12
    assert all(
        row["status"] == "invalidated_input_drift"
        and row["sensitivity"] is None
        and "baseline" not in row
        for row in result["records"]
    )
    assert result["summary"]["candidate_targets"] == result["summary"]["baseline_targets"] == 0
    assert result["summary"]["all_requested_verified"] is False
    assert (output / "foreign-note.txt").read_bytes() == b"keep foreign file"
    assert json.loads((output / "report.json").read_bytes()) == result


def test_successful_report_checks_before_and_after_writing_and_never_outputs_masks(tmp_path):
    output = tmp_path / "new-report"
    phases = []
    result = probe.publish_report(
        output, publication_fixture(), lambda: phases.append((output / "report.json").exists())
    )
    assert phases == [False, True]
    assert result["summary"]["all_requested_verified"] is True
    assert sorted(p.name for p in output.iterdir()) == ["report.json"]


def test_existing_output_is_refused_before_audit_or_any_write(tmp_path):
    output = tmp_path / "old-report"
    output.mkdir()
    (output / "report.json").write_bytes(b"retain historical result")
    calls = []
    with pytest.raises(FileExistsError):
        probe.publish_report(output, publication_fixture(), lambda: calls.append(True))
    assert not calls and (output / "report.json").read_bytes() == b"retain historical result"


@pytest.fixture
def synthetic_run(tmp_path, monkeypatch, scenario):
    runtime = {"synthetic_runtime": True}
    (tmp_path / ".gitignore").write_text("output/\n", encoding="utf-8")

    def frozen(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else json.dumps(value, allow_nan=False).encode()
        path.write_bytes(raw)
        return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    source_pins = [frozen(name, b"# synthetic source snapshot\n") for name in probe.SOURCES]
    loaded = {
        value["path"]: value["sha256"]
        for value in source_pins
        if value["path"] in probe._LOADED_SOURCE_HASHES
    }
    monkeypatch.setattr(probe, "_LOADED_SOURCE_HASHES", loaded)
    fixture_pin = frozen("prior/fixture.json", {"synthetic": True})
    primary, old_records, selected = [], {}, []
    counts = probe.uv.region_counts(
        scenario[1],
        scenario[2]["texel_rows_columns"],
        scenario[2]["region_bits"],
        scenario[2]["rejection_partition"],
    )
    for source, ages in probe.uv.COHORT.items():
        for age in ages:
            sample_id = f"{source}--sam-{age:03d}"
            row = {
                "sample_id": sample_id,
                "source_id": source,
                "target_age": age,
                "source_age_label": {"fgnet-004a63": 63, "fgnet-082a27": 27, "fgnet-006a55": 55}[
                    source
                ],
                "source_frame": {"synthetic": True},
                "input": fixture_pin,
                "target_fit": {"synthetic": True},
            }
            selected.append({"registration": row})
            old_records[sample_id] = {
                "correspondence": fixture_pin,
                "counts": copy.deepcopy(counts),
            }
            primary.append(
                {
                    "sample_id": sample_id,
                    "pixel_comparison": {"exact": True},
                    "layer_pixel_counts": {"synthetic": True},
                    "decomposition": {"synthetic": True},
                }
            )
    protocol = json.loads((_PATH.parent.parent / "docs/mask-candidate-v1.json").read_bytes())
    roles = {
        "protocol": frozen("prior/protocol.json", protocol),
        "mask_report": frozen("prior/report.json", {"records": primary}),
        "mask_audit": frozen("prior/audit.json", {"synthetic": True}),
        "uv_report": frozen("prior/uv.json", {"synthetic": True}),
    }
    plan = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "runtime": runtime,
        "roles": roles,
        "inputs": [*source_pins, fixture_pin, *roles.values()],
    }
    plan_path = tmp_path / "study-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(probe.uv, "runtime_fingerprint", lambda: runtime)
    monkeypatch.setattr(probe, "derive_input_pins", lambda metadata: [])
    monkeypatch.setattr(probe.workbench, "validate_evidence", lambda *args: (selected, old_records))
    baseline_calls = []

    def baseline(inputs, item, old, saved):
        baseline_calls.append(item["registration"]["sample_id"])
        return copy.deepcopy(scenario)

    monkeypatch.setattr(probe, "_baseline_record", baseline)
    return SimpleNamespace(
        args=SimpleNamespace(
            root=tmp_path, study_plan=plan_path, output_dir=tmp_path / "output/research/candidate"
        ),
        scenario=scenario,
        baseline=baseline,
        baseline_calls=baseline_calls,
        source_path=tmp_path / "tools/mask_candidate_probe.py",
        plan=plan,
    )


def test_run_completes_all_baselines_before_first_counterfactual_and_keeps_unknown_age(
    synthetic_run, monkeypatch
):
    original = probe.evaluate_counterfactual
    calls = []

    def evaluate(*args):
        assert len(synthetic_run.baseline_calls) == 12
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(probe, "evaluate_counterfactual", evaluate)
    report = probe.run(synthetic_run.args)
    assert len(calls) == 12
    assert report["summary"]["candidate_targets"] == report["summary"]["baseline_targets"] == 12
    assert report["summary"]["all_requested_verified"] is True
    assert all(
        row["source_age"] == {"value": None, "method": "unknown", "calibration_id": None}
        and row["sensitivity"]["released_texels"] == 1
        for row in report["records"]
    )
    assert (
        report["human_review_completed"]
        is report["g3_complete"]
        is report["usable_mask_candidate_accepted"]
        is False
    )


def test_one_failed_baseline_prevents_every_counterfactual_and_retains_twelve_requests(
    synthetic_run, monkeypatch
):
    def baseline(inputs, item, old, saved):
        if item["registration"]["sample_id"].endswith("--sam-063"):
            raise ValueError("synthetic original-mask mismatch")
        return synthetic_run.baseline(inputs, item, old, saved)

    monkeypatch.setattr(probe, "_baseline_record", baseline)
    monkeypatch.setattr(
        probe, "evaluate_counterfactual", lambda *args: pytest.fail("candidate gate bypassed")
    )
    report = probe.run(synthetic_run.args)
    assert len(report["records"]) == 12
    assert report["summary"]["candidate_targets"] == 0
    assert report["summary"]["baseline_targets"] == 11
    assert report["summary"]["all_baselines_verified"] is False
    assert all(row["sensitivity"] is None for row in report["records"])


def test_one_counterfactual_failure_withholds_every_other_candidate_result(
    synthetic_run, monkeypatch
):
    original = probe.evaluate_counterfactual
    calls = 0

    def evaluate(*args):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise ValueError("synthetic candidate inconsistency")
        return original(*args)

    monkeypatch.setattr(probe, "evaluate_counterfactual", evaluate)
    report = probe.run(synthetic_run.args)
    assert calls == len(report["records"]) == 12
    assert report["summary"]["all_baselines_verified"] is True
    assert report["summary"]["all_requested_verified"] is False
    assert report["summary"]["candidate_targets"] == 0
    assert all(row["sensitivity"] is None for row in report["records"])


@pytest.mark.parametrize("kind", ["source", "plan", "runtime"])
def test_late_source_plan_or_runtime_drift_invalidates_every_prepared_value(
    synthetic_run, monkeypatch, kind
):
    original = probe.evaluate_counterfactual
    changed = False

    def evaluate(*args):
        nonlocal changed
        result = original(*args)
        if not changed:
            if kind == "source":
                synthetic_run.source_path.write_bytes(b"changed after all12 baseline snapshots")
            elif kind == "plan":
                synthetic_run.args.study_plan.write_text(
                    json.dumps({**synthetic_run.plan, "late_change": True}), encoding="utf-8"
                )
            else:
                monkeypatch.setattr(probe.uv, "runtime_fingerprint", lambda: {"runtime": "changed"})
            changed = True
        return result

    monkeypatch.setattr(probe, "evaluate_counterfactual", evaluate)
    report = probe.run(synthetic_run.args)
    assert len(report["records"]) == 12
    assert report["summary"]["all_requested_verified"] is False
    assert report["summary"]["candidate_targets"] == report["summary"]["baseline_targets"] == 0
    assert all(
        row["status"] == "invalidated_input_drift"
        and row["sensitivity"] is None
        and "baseline" not in row
        for row in report["records"]
    )


def test_loaded_source_mismatch_is_rejected_before_baseline_decode(synthetic_run, monkeypatch):
    monkeypatch.setattr(probe, "_LOADED_SOURCE_HASHES", {"tools/mask_candidate_probe.py": "0" * 64})
    with pytest.raises(ValueError, match="Loaded Python implementation"):
        probe.run(synthetic_run.args)
    assert not synthetic_run.baseline_calls and not synthetic_run.args.output_dir.exists()


@pytest.mark.parametrize(
    "problem", ["source_age", "arms", "transition", "results_seen", "quality", "human_review"]
)
def test_protocol_rejects_age_defaults_mislabelled_upper_bound_or_acceptance_promotion(problem):
    protocol = json.loads((_PATH.parent.parent / "docs/mask-candidate-v1.json").read_bytes())
    probe._protocol(protocol)
    if problem == "source_age":
        protocol["cohort"]["api_source_age"] = {
            "value": 50,
            "method": "default",
            "calibration_id": None,
        }
    elif problem == "arms":
        protocol["arms"][1] = "usable_mask_candidate"
    elif problem == "transition":
        protocol["counterfactual"]["only_transition"] = [4, 6]
    elif problem == "results_seen":
        protocol["observations"]["candidate_results_seen_before_freeze"] = True
    elif problem == "quality":
        protocol["flags"]["usable_mask_candidate_accepted"] = True
    else:
        protocol["flags"]["human_review_completed"] = True
    with pytest.raises(ValueError):
        probe._protocol(protocol)
