"""Synthetic route-selection and evidence guards, without real-data calibration."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from agemorph3d.age_geometry import source_frame
from agemorph3d.tddfa import TddfaResult

_PATH = Path(__file__).resolve().parents[2] / "tools/age_route_probe.py"
_SPEC = importlib.util.spec_from_file_location("age_route_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def pin(root, path):
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def selection_case(values=(1.0, 0.4, 0.3)):
    records = []
    for route, value in zip(probe._ROUTES, values, strict=True):
        for subject in ("a", "b", "c"):
            records.append(
                dict(
                    route=route,
                    status="ok",
                    subject_id=subject,
                    source_id=subject + "-source",
                    real_target_id=subject + "-target",
                    endpoint_neutral_rms=value,
                    displacement_rms=0.1,
                    identity_margin=0.2,
                )
            )
    resets = [
        dict(sample_id=f"source-{index}", route=route, exact_reset=True)
        for route in probe._ROUTES[1:]
        for index in range(8)
    ]
    calibration = {
        "strength_per_year": 0.5,
        "loio": [
            {"status": "ok", "strength_per_year": 0.3},
            {"status": "ok", "strength_per_year": 0.4},
        ],
    }
    return records, calibration, resets


def choose(case):
    return probe.choose_route(*case, expected=3)


def test_research_ranking_uses_smallest_eligible_endpoint_error_and_keeps_quality_closed():
    result = choose(selection_case())
    assert result["research_route_choice"] == "sam_difference"
    assert result["production_route_selected"] is None
    assert all(
        not result[key]
        for key in ("identity_quality_accepted", "years_calibrated", "full_20_70_range_accepted")
    )


@pytest.mark.parametrize("values", [(1, 1.2, 1.3), (1, 1 - 1e-14, 2), (1, 0.3, 0.3 + 1e-14)])
def test_nonimprovement_and_numerical_ties_keep_static_fallback(values):
    assert choose(selection_case(values))["research_route_choice"] == "static_fallback"


@pytest.mark.parametrize(
    "failure", ["negative_full", "negative_fold", "unavailable_fold", "empty_loio"]
)
def test_bfm_sign_and_complete_loio_are_hard_gates(failure):
    records, calibration, resets = selection_case((1, 0.1, 2))
    if failure == "negative_full":
        calibration["strength_per_year"] = -0.2
    elif failure == "negative_fold":
        calibration["loio"][0]["strength_per_year"] = -0.2
    elif failure == "unavailable_fold":
        calibration["loio"][0] = {"status": "unavailable"}
    else:
        calibration["loio"] = []
    result = choose((records, calibration, resets))
    assert result["research_route_choice"] == "static_fallback"
    assert not result["gates"]["bfm_calibrated"]["sign_gate"]


@pytest.mark.parametrize("failure", ["missing", "duplicate", "inexact"])
def test_every_eight_unique_source_resets_are_required(failure):
    records, calibration, resets = selection_case((1, 0.1, 0.3))
    own = [row for row in resets if row["route"] == "bfm_calibrated"]
    if failure == "missing":
        resets.remove(own[-1])
    elif failure == "duplicate":
        own[-1]["sample_id"] = own[0]["sample_id"]
    else:
        own[-1]["exact_reset"] = False
    result = choose((records, calibration, resets))
    assert not result["gates"]["bfm_calibrated"]["eligible"]
    assert result["research_route_choice"] == "sam_difference"


@pytest.mark.parametrize("failure", ["missing", "failed", "wrong_pair"])
def test_incomplete_or_mismatched_baseline_cannot_choose_a_route(failure):
    records, calibration, resets = selection_case()
    baseline = next(row for row in records if row["route"] == "no_change")
    if failure == "missing":
        records.remove(baseline)
    elif failure == "failed":
        baseline["status"] = "failed"
    else:
        baseline["real_target_id"] = "different-pair"
    result = choose((records, calibration, resets))
    assert result["research_route_choice"] == "static_fallback"
    assert not any(gate["eligible"] for gate in result["gates"].values())


@pytest.fixture
def raw_source():
    return TddfaResult(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=np.array([[0, 0, 0], [2, 0, 0], [0, 4, 0], [1, 1, 2]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64),
        projection=np.eye(3, 4, dtype=np.float32),
        roi=(0, 0, 120, 120),
        topology_sha256="a" * 64,
    )


def test_sam_candidate_exact_source_reset_needs_no_generated_fits(raw_source):
    result = probe._candidate(
        "sam_difference", raw_source, None, None, None, None, np.zeros((12, 10)), 35.5, 35.5
    )
    assert result is raw_source
    assert result.vertices.tobytes() == raw_source.vertices.tobytes()


def test_identity_proxy_changes_with_edited_geometry_without_any_coefficient_claim():
    genuine, impostor = np.zeros((4, 3)), np.ones((4, 3))
    frame = {"source_to_canonical_uniform_scale": 2.0}
    baseline = probe.identity_geometry_proxy(genuine, genuine, {"other": impostor}, frame)
    shifted = probe.identity_geometry_proxy(impostor, genuine, {"other": impostor}, frame)
    assert baseline["identity_margin"] > 0 and shifted["identity_margin"] < 0
    assert shifted["genuine_rms"] == pytest.approx(2 * np.sqrt(3))
    assert shifted["nearest_impostor_rms"] == 0
    unavailable = probe.identity_geometry_proxy(genuine, genuine, {}, frame)
    assert unavailable["identity_margin"] is None and unavailable["impostor_count"] == 0


def test_expected_cohort_uses_exact_labels_not_nearest_age_or_other_groups():
    manifest = {
        "bridge_cases": [
            {
                "sample_id": "fgnet-001a25",
                "subject_id": "001",
                "source_status": "passed",
                "group": "development",
                "source_age": {"value": 25},
                "target_runs": [{"target_age": 20}, {"target_age": 45}],
            }
        ],
        "adult_images": [
            dict(group=group, subject_id=subject, source_age=age, path=path)
            for group, subject, age, path in (
                ("development", "001", 20, "001A20.JPG"),
                ("development", "001", 44, "001A44.JPG"),
                ("development", "002", 45, "002A45.JPG"),
                ("evaluation_research_holdout", "001", 45, "001A45.JPG"),
            )
        ],
    }
    assert probe._expected_matches(manifest) == {
        (
            "001",
            "fgnet-001a25",
            "fgnet-001a20",
            "fgnet-001a25--sam-020",
            "fgnet-001a25--sam-025",
            25,
            20,
        )
    }


@pytest.fixture
def saved_study(tmp_path, raw_source):
    vertices = raw_source.vertices
    coordinates = (np.arange(204) % vertices.size).reshape(68, 3)
    topology = tmp_path / "topology.npz"
    np.savez(topology, triangles=raw_source.triangles, keypoint_coordinates=coordinates)
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for array in (
        np.array([len(vertices), len(raw_source.triangles)], dtype="<i8"),
        raw_source.triangles.astype("<i8"),
        coordinates.astype("<i8"),
    ):
        digest.update(array.tobytes(order="C"))
    fit_path = tmp_path / "fit.npz"
    arrays = dict(
        vertices=vertices,
        neutral_vertices=vertices.astype(np.float64),
        shape=raw_source.shape,
        expr=raw_source.expr,
        projection=raw_source.projection,
        roi=np.array(raw_source.roi),
    )
    np.savez(fit_path, **arrays)
    image = tmp_path / "001A20.JPG"
    image.write_bytes(b"synthetic input pin, no image decoding")
    original = pin(tmp_path, image)
    manifest = {
        "adult_images": [dict(original, subject_id="001", source_age=20, group="development")],
        "bridge_cases": [],
    }
    row = dict(
        sample_id="fgnet-001a20",
        subject_id="001",
        source_age=20,
        role="original",
        data_group="development",
        status="ok",
        input=original,
        fit_artifact=pin(tmp_path, fit_path),
        topology_sha256=digest.hexdigest(),
        canonical_frame=source_frame(vertices),
    )
    report = {
        "study": "longitudinal",
        "fit_records": [row],
        "topology_artifact": pin(tmp_path, topology),
    }
    basis = {
        "tri": raw_source.triangles,
        "keypoints": coordinates.reshape(-1),
        "w_exp": np.zeros((vertices.size, 10)),
    }
    return SimpleNamespace(
        root=tmp_path,
        manifest=manifest,
        report=report,
        row=row,
        basis=basis,
        fit_path=fit_path,
        arrays=arrays,
    )


def test_study_loader_restores_neutral_fit_in_pinned_original_frame(saved_study):
    item = saved_study
    probe._verify_descendants(item.root, item.report)
    jobs, records, fits, neutrals = probe._load_study(
        item.root, item.report, item.manifest, "longitudinal", item.basis
    )
    assert set(jobs) == set(records) == set(fits) == set(neutrals) == {"fgnet-001a20"}
    np.testing.assert_array_equal(neutrals["fgnet-001a20"], item.arrays["vertices"])


@pytest.mark.parametrize("failure", ["age", "group", "source_frame", "neutral_vertices"])
def test_study_loader_rejects_metadata_or_neutralization_tampering(saved_study, failure):
    item = saved_study
    if failure == "age":
        item.row["source_age"] = 21
    elif failure == "group":
        item.row["data_group"] = "evaluation_research_holdout"
    elif failure == "source_frame":
        item.row["canonical_frame"]["source_center"][0] += 1
    else:
        np.savez(item.fit_path, **dict(item.arrays, neutral_vertices=item.arrays["vertices"] + 1))
    with pytest.raises(ValueError):
        probe._load_study(item.root, item.report, item.manifest, "longitudinal", item.basis)


def test_study_artifact_hash_tampering_is_rejected_before_loading(saved_study):
    item = saved_study
    item.fit_path.write_bytes(b"replaced fit")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        probe._verify_descendants(item.root, item.report)


def test_existing_output_is_preserved_before_any_analysis(tmp_path, monkeypatch):
    output = tmp_path / "result"
    output.mkdir()
    marker = output / "report.json"
    marker.write_text("preserve original evidence", encoding="utf-8")
    monkeypatch.setattr(probe, "build_report", lambda args: pytest.fail("must not analyze"))
    assert (
        probe.main(
            ["--root", str(tmp_path), "--calibration-report", "cal.json", "--output-dir", "result"]
        )
        == 1
    )
    assert marker.read_text(encoding="utf-8") == "preserve original evidence"


@pytest.fixture
def analysis_plan(tmp_path, monkeypatch):
    names = (
        "protocol",
        "protocol_manifest",
        "study_plan",
        "run_freeze",
        "calibration_report",
        "longitudinal_report",
        "generated_report",
        "matched_report",
        "bfm",
        "direction",
    )
    args = SimpleNamespace(root=tmp_path, **{name: tmp_path / (name + ".json") for name in names})
    write_json(args.protocol, {"protocol_id": "synthetic-N3", "parent_protocol_id": "synthetic-N0"})
    write_json(args.protocol_manifest, {"protocol_id": "synthetic-N0"})
    for name in names[4:]:
        write_json(getattr(args, name), {})
    paths = [
        args.protocol,
        args.protocol_manifest,
        args.direction,
        args.bfm,
        args.longitudinal_report,
        args.generated_report,
        args.matched_report,
    ]
    plan = {
        "protocol_id": "synthetic-N3",
        "inputs": {
            path.name: {key: value for key, value in pin(tmp_path, path).items() if key != "path"}
            for path in paths
        },
    }
    freeze = {
        "inputs": {
            args.calibration_report.name: {
                key: value
                for key, value in pin(tmp_path, args.calibration_report).items()
                if key != "path"
            }
        }
    }
    write_json(args.study_plan, plan)
    write_json(args.run_freeze, freeze)
    monkeypatch.setattr(probe, "fit_bfm_scale", lambda *args: pytest.fail("no calibration allowed"))
    return args, plan, freeze


def test_analysis_requires_each_supplied_input_to_be_bound_before_calibration(analysis_plan):
    args, plan, freeze = analysis_plan
    del plan["inputs"][args.bfm.name]
    write_json(args.study_plan, plan)
    with pytest.raises(ValueError, match="bind every supplied"):
        probe.build_report(args)


def test_preanalysis_freeze_must_bind_new_calibration_output(analysis_plan):
    args, plan, freeze = analysis_plan
    write_json(args.run_freeze, {"inputs": {}})
    with pytest.raises(ValueError, match="bind every supplied"):
        probe.build_report(args)


def test_analysis_freezes_cannot_disagree_about_an_input(analysis_plan):
    args, plan, freeze = analysis_plan
    freeze["inputs"][args.protocol.name] = {"sha256": "a" * 64, "bytes": 1}
    write_json(args.run_freeze, freeze)
    with pytest.raises(ValueError, match="freezes disagree"):
        probe.build_report(args)


def test_bound_inputs_pass_the_guard_without_computing_a_scale(analysis_plan, monkeypatch):
    args, plan, freeze = analysis_plan

    class InputsVerified(Exception):
        pass

    def stop_before_numeric_artifact_loading(*args):
        raise InputsVerified

    monkeypatch.setattr(probe, "_verify_descendants", stop_before_numeric_artifact_loading)
    with pytest.raises(InputsVerified):
        probe.build_report(args)
