"""Synthetic common-UV, original-anchor priority and BLEND transport tests."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

_PATH = Path(__file__).resolve().parents[2] / "tools/blend_display_probe.py"
_SPEC = importlib.util.spec_from_file_location("blend_display_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def make_asset(root, sample_id, rgba, vertices=None):
    directory = root / sample_id
    directory.mkdir()
    vertices = (
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4") if vertices is None else vertices
    )
    normals = np.tile(np.array([[0, 0, 1]], dtype="<f4"), (3, 1))
    triangles = np.array([[0, 1, 2]], dtype="<u4")
    uv = np.array([[0, 0], [1, 0], [0, 1]], dtype="<f4")
    output = io.BytesIO()
    Image.fromarray(rgba).save(output, "PNG")
    png = output.getvalue()
    texture = SimpleNamespace(png=png, gltf_uv=uv)
    extras = {
        "asset_mode": "static",
        "source_age": dict(probe.UNKNOWN_AGE),
        "topology_id": "synthetic",
        "coordinate_metadata": {"frame": "synthetic-source"},
        "base_texture": {"age_generated": False},
    }
    glb = probe._encode_glb(vertices, normals, triangles, extras, texture)
    png_path, glb_path = directory / "atlas.png", directory / "mesh.glb"
    png_path.write_bytes(png)
    glb_path.write_bytes(glb)
    geometry = probe._decode(glb)[3]
    return {"atlas": probe._pin(root, png_path), "glb": probe._pin(root, glb_path)}, geometry


@pytest.fixture
def case(tmp_path):
    root = tmp_path
    (root / "output/research").mkdir(parents=True)
    for name in probe._CODE + probe._PROTOCOLS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic frozen source\n", encoding="utf-8")
    rows, originals, invariants = [], [], {}
    for source_id, label in (("known", 45), ("unknown", None)):
        for age in (20, 45, 70):
            rgba = np.zeros((4, 4, 4), dtype=np.uint8)
            column = (age - 20) // 25
            rgba[:, column, :] = [255, 0, 0, 255] if age == 20 else [0, 0, 255, 255]
            artifacts, geometry = make_asset(root, f"{source_id}-{age}", rgba)
            invariants[source_id] = geometry
            rows.append(
                {
                    "sample_id": f"{source_id}-{age}",
                    "source_id": source_id,
                    "status": "ok",
                    "target_age": age,
                    "source_age_label": label,
                    "source_age": dict(probe.UNKNOWN_AGE),
                    "capabilities": {"age_morph": False, "age_texture": False},
                    "artifacts": artifacts,
                    **geometry,
                }
            )
        rgba = np.zeros((4, 4, 4), dtype=np.uint8)
        rgba[:, 3, :] = [0, 255, 0, 255]
        artifacts, _ = make_asset(root, f"{source_id}-original", rgba)
        originals.append(
            {
                "sample_id": source_id,
                "status": "ok",
                "source_age": dict(probe.UNKNOWN_AGE),
                "group": "development",
                "label_source_age": label,
                "reset_status": "passed" if label is not None else "source_age_unknown",
                "artifacts": artifacts,
            }
        )
    registration = {
        "protocol_id": "agemorph3d-target-uv-v1",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "records": rows,
        "source_geometry_invariants": invariants,
    }
    reset = {
        "protocol_id": "agemorph3d-source-reset-v1",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "records": originals,
    }
    registration_path, reset_path, plan_path = (
        root / "registration.json",
        root / "reset.json",
        root / "plan.json",
    )
    plan = {
        "protocol_id": probe.PROTOCOL_ID,
        "epsilon_years": 0.001,
        "atlas_size": 4,
        "expected_sources": 2,
        "expected_generated": 6,
        "expected_intervals": 4,
    }

    def repin():
        write_json(registration_path, registration)
        write_json(reset_path, reset)
        plan["registration_report"] = probe._pin(root, registration_path)
        plan["source_reset_report"] = probe._pin(root, reset_path)
        pins = [plan["registration_report"], plan["source_reset_report"]]
        pins += [pin for row in rows + originals for pin in row["artifacts"].values()]
        pins += [probe._pin(root, root / name) for name in probe._CODE + probe._PROTOCOLS]
        plan["inputs"] = {
            pin["path"]: {"sha256": pin["sha256"], "bytes": pin["bytes"]} for pin in pins
        }
        write_json(plan_path, plan)

    repin()
    return SimpleNamespace(
        root=root,
        args=SimpleNamespace(
            root=root, study_plan=plan_path, output_dir=root / "output/research/new-output"
        ),
        registration=registration,
        reset=reset,
        rows=rows,
        originals=originals,
        plan=plan,
        repin=repin,
    )


def test_original_source_priority_exact_bytes_and_unknown_condition_policy(case):
    report = probe.run(case.args)
    assert report["summary"]["records"] == 15
    assert report["summary"]["pair_probes"] == 5
    assert report["summary"]["exact_original_source_cases"] == 1
    assert report["summary"]["unknown_source_anchors"] == 1
    assert report["summary"]["all_geometry_and_uv_hashes_exact"]
    assert not report["service_ready"] and not report["g3_complete"]
    assert (
        not report["production_continuity_accepted"] and not report["age_texture_quality_accepted"]
    )
    exact = next(row for row in report["records"] if row["kind"] == "source_exact")
    original = case.originals[0]
    for key in ("atlas", "glb"):
        assert exact["artifacts"][key]["sha256"] == original["artifacts"][key]["sha256"]
    assert exact["original_source_bytes_exact"]
    assert exact["inputs"]["active_anchors"][0]["kind"] == "original_source"
    for row in report["records"]:
        assert row["source_age"] == probe.UNKNOWN_AGE and row["unknown_rgba_zero"]
        if row["source_id"] == "unknown":
            assert row["source_reset_status"] == "SOURCE_AGE_UNKNOWN"
            assert row["kind"] != "source_exact"
    # The SAM(45) blue surface is excluded in favor of green original-photo support.
    left = next(
        row
        for row in report["records"]
        if row["source_id"] == "known" and row["target_age"] == 32.499
    )
    with Image.open(probe._path(case.root, left["artifacts"]["atlas"]["path"])) as image:
        rgba = np.asarray(image)
    assert np.any(rgba[:, :, 1] > 0) and not np.any(rgba[:, :, 2])


def test_blend_and_mask_baseline_share_exact_png_geometry_but_material_differs(case):
    report = probe.run(case.args)
    for row in report["records"]:
        data = probe._path(case.root, row["artifacts"]["glb"]["path"]).read_bytes()
        document, _, png, geometry = probe._decode(data)
        assert geometry == row["expected_geometry"]
        assert probe._hash(png) == row["artifacts"]["atlas"]["sha256"]
        mode = document["materials"][0]["alphaMode"]
        if row["kind"] == "source_exact":
            assert mode == "MASK" and "mask_glb" not in row["artifacts"]
            control = probe._path(
                case.root, row["artifacts"]["blend_control_glb"]["path"]
            ).read_bytes()
            control_document, _, control_png, control_geometry = probe._decode(control)
            assert control_geometry == geometry and control_png == png
            assert control_document["materials"][0]["alphaMode"] == "BLEND"
            assert row["source_material_control_kind"] == "source_material_control"
        else:
            assert mode == "BLEND" and "alphaCutoff" not in document["materials"][0]
            mask = probe._path(case.root, row["artifacts"]["mask_glb"]["path"]).read_bytes()
            mask_document, _, mask_png, mask_geometry = probe._decode(mask)
            assert mask_geometry == geometry and mask_png == png
            assert mask_document["materials"][0]["alphaMode"] == "MASK"
            assert mask_document["materials"][0]["alphaCutoff"] == 0.5
    assert any(row["fractional_alpha_texels"] > 0 for row in report["records"])


def test_interval_pairs_bind_actual_cases_and_recompute_support_changes(case):
    report = probe.run(case.args)
    records = {row["sample_id"]: row for row in report["records"]}
    assert sum(pair["kind"] == "interval_midpoint" for pair in report["pair_probes"]) == 4
    for pair in report["pair_probes"]:
        assert records[pair["before_id"]]["target_age"] == pair["before_age"]
        assert records[pair["after_id"]]["target_age"] == pair["after_age"]
        assert pair["after_age"] - pair["before_age"] == pytest.approx(0.002)
        assert pair["support_xor_texels"] == 8
        assert pair["numeric_display_step"]["black_composite_rms_channel"] >= 0
        if pair["kind"] == "source_neighborhood":
            assert records[pair["source_exact_id"]]["kind"] == "source_exact"


@pytest.mark.parametrize("target", ["report", "atlas", "glb", "source"])
def test_frozen_input_drift_fails_before_creating_output(case, target):
    if target == "report":
        path = probe._path(case.root, case.plan["registration_report"]["path"])
    elif target == "source":
        path = case.root / probe._CODE[0]
    else:
        path = probe._path(case.root, case.rows[0]["artifacts"][target]["path"])
    with path.open("ab") as stream:
        stream.write(b"drift")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


@pytest.mark.parametrize(
    "change", ["geometry", "api_age", "label", "holdout", "duplicate", "count", "boundary"]
)
def test_inconsistent_geometry_provenance_and_cohort_are_rejected(case, change):
    if change == "geometry":
        changed = np.array([[0, 0, 0], [2, 0, 0], [0, 1, 0]], dtype="<f4")
        rgba = np.zeros((4, 4, 4), dtype=np.uint8)
        case.rows[0]["artifacts"], _ = make_asset(case.root, "changed", rgba, changed)
    elif change == "api_age":
        case.originals[0]["source_age"] = {"value": 45, "method": "user", "calibration_id": None}
    elif change == "label":
        case.originals[0]["label_source_age"] = 44
    elif change == "holdout":
        case.originals[0]["group"] = "evaluation_research_holdout"
    elif change == "duplicate":
        case.rows.append(case.rows[0])
    elif change == "count":
        case.plan["expected_intervals"] += 1
    else:
        case.rows[0]["target_age"] = 21
    case.repin()
    with pytest.raises(ValueError):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_omitted_asset_pin_rejected_even_when_report_is_pinned(case):
    del case.plan["inputs"][case.rows[0]["artifacts"]["atlas"]["path"]]
    write_json(case.args.study_plan, case.plan)
    with pytest.raises(ValueError, match="explicitly frozen"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_existing_output_and_outside_workspace_are_rejected(case, capsys):
    case.args.output_dir.mkdir()
    sentinel = case.args.output_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="must not already exist"):
        probe.run(case.args)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert (
        probe.main(
            ["--root", str(case.root), "--study-plan", "../escape.json", "--output-dir", "out"]
        )
        == 2
    )
    assert "within the selected workspace" in capsys.readouterr().err


def test_output_cannot_leave_ignored_research_directory(case):
    case.args.output_dir = case.root / "unsafe-untracked-output"
    with pytest.raises(ValueError, match="new subdirectory under workspace output/research"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()
