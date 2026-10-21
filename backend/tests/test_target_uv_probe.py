"""Tiny synthetic offline registration and provenance checks; no real projections."""

import importlib.util
import io
import json
import struct
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from agemorph3d.tddfa import TddfaResult
from PIL import Image

_PATH = Path(__file__).resolve().parents[2] / "tools/target_uv_probe.py"
_SPEC = importlib.util.spec_from_file_location("target_uv_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path
    yy, xx = np.mgrid[:16, :16]
    rgb = np.stack((xx * 10, yy * 10, xx * 3 + yy), axis=-1).astype(np.uint8)
    source = TddfaResult(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=np.array([[2, 115, 0], [10, 115, 0], [2, 107, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int64),
        projection=np.eye(3, 4, dtype=np.float32),
        roi=(0.0, 0.0, 120.0, 120.0),
        topology_sha256="ab" * 32,
    )
    projection = source.projection.copy()
    projection[0, 3] = 2
    target = replace(source, projection=projection)
    uv = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float32)
    image_path, allowed_path, occluded_path = [
        root / name for name in ("target.png", "allowed.png", "occluded.png")
    ]
    Image.fromarray(rgb).save(image_path)
    Image.fromarray(np.full((16, 16), 255, dtype=np.uint8)).save(allowed_path)
    Image.fromarray(np.zeros((16, 16), dtype=np.uint8)).save(occluded_path)
    fit_path = root / "fit.npz"
    np.savez_compressed(fit_path, vertices=target.vertices)
    job = {
        "sample_id": "source--sam-020",
        "reference_source_id": "source",
        "subject_id": "dev-a",
        "source_age": None,
        "target_age": 20,
        "role": "sam_generated",
        "input": probe._pin(root, image_path),
    }
    records = {
        job["sample_id"]: {
            "sample_id": job["sample_id"],
            "image_size": [16, 16],
            "fit_artifact": probe._pin(root, fit_path),
            "status": "ok",
        }
    }
    jobs = {job["sample_id"]: job}
    fits = {"source": source, job["sample_id"]: target}
    paths = {
        key: root / filename
        for key, filename in {
            "protocol": "protocol.json",
            "protocol_manifest": "manifest.json",
            "generated_report": "generated.json",
            "selection": "selection.json",
            "study_plan": "plan.json",
            "mask_review": "review.json",
            "bfm": "bfm.npz",
            "uv": "uv.npz",
        }.items()
    }
    np.savez_compressed(
        paths["bfm"],
        w_exp=np.zeros((9, 10), dtype=np.float32),
        tri=source.triangles,
        keypoints=np.arange(3),
    )
    np.savez_compressed(paths["uv"], uv=uv, topology_sha256=source.topology_sha256)
    protocol = {
        "protocol_id": "agemorph3d-target-uv-v1",
        "parent_protocol_id": "synthetic-n0",
        "expected_generated_images": 1,
        "expected_source_images": 1,
        "atlas_size": 4,
    }
    write_json(paths["protocol"], protocol)
    write_json(paths["protocol_manifest"], {"protocol_id": "synthetic-n0"})
    generated = {
        "inputs": {"protocol_manifest": probe._pin(root, paths["protocol_manifest"])},
        "expression_basis": {"asset": probe._pin(root, paths["bfm"])},
        "fit_records": [
            {"sample_id": "original-failed", "status": "failed", "error_code": "NO_FACE"},
            {"sample_id": "aligned-failed", "status": "failed", "error_code": "MULTI_FACE"},
        ],
    }
    write_json(paths["generated_report"], generated)
    write_json(
        paths["selection"],
        {"research_route_choice": "static_fallback", "production_route_selected": None},
    )
    review = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "target_records": [
            {
                "sample_id": job["sample_id"],
                "input": job["input"],
                "target_fit": records[job["sample_id"]]["fit_artifact"],
                "allowed_mask": probe._pin(root, allowed_path),
                "occluded_mask": probe._pin(root, occluded_path),
                "reviewer": "codex_visual_review",
                "status": "reviewed_conservative_exclusion",
                "method": "Synthetic whole-frame support",
                "notes": ["Synthetic exclusion review; not segmentation truth"],
                "allowed_pixels": 256,
                "excluded_occluder_pixels": 0,
            }
        ],
    }
    write_json(paths["mask_review"], review)

    def repin():
        write_json(paths["mask_review"], review)
        write_json(
            paths["study_plan"],
            {
                "protocol_id": protocol["protocol_id"],
                "inputs": {
                    path.relative_to(root).as_posix(): {
                        key: value for key, value in probe._pin(root, path).items() if key != "path"
                    }
                    for name, path in paths.items()
                    if name != "study_plan"
                },
            },
        )

    repin()

    def load_study(given_root, report, manifest, study, basis):
        assert given_root == root and report == generated
        assert manifest["protocol_id"] == "synthetic-n0" and study == "generated"
        np.testing.assert_array_equal(basis["tri"], source.triangles)
        return jobs, records, fits, {}

    monkeypatch.setattr(probe, "_load_study", load_study)
    args = SimpleNamespace(
        root=root,
        output_dir=root / "new-output",
        uv_sha256=probe._pin(root, paths["uv"])["sha256"],
        **paths,
    )
    return SimpleNamespace(
        root=root,
        paths=paths,
        args=args,
        jobs=jobs,
        records=records,
        fits=fits,
        source=source,
        target=target,
        uv=uv,
        review=review,
        generated=generated,
        protocol=protocol,
        repin=repin,
    )


def test_target_own_full_fit_projection_and_source_unknown_age_survive_transport(case):
    report = probe.run(case.args)
    row = report["records"][0]
    assert row["status"] == "ok" and row["projection"] == case.target.projection.tolist()
    assert report["summary"]["all_requested_glb_roundtrips_passed"]
    assert report["retained_prior_fit_failures"] == case.generated["fit_records"]
    assert row["source_age_label"] is None and row["source_age"] == probe.UNKNOWN_AGE
    assert row["asset_mode"] == "static" and row["texture_url"] is None
    assert row["capabilities"] == {"age_morph": False, "age_texture": False}
    with np.load(
        probe._path(case.root, row["artifacts"]["samples"]["path"]), allow_pickle=False
    ) as saved:
        # Independent target-x+2 expectation: a source-camera substitution gives red=20.
        np.testing.assert_array_equal(saved["rgba"][0, 0], [40, 60, 18, 255])
        assert np.all(saved["rgba"][~saved["coverage"]] == 0)
        np.testing.assert_array_equal(saved["coverage"], saved["classification"] == 6)
    for name in ("classification", "coverage"):
        with Image.open(probe._path(case.root, row["artifacts"][name]["path"])) as image:
            assert image.mode == "L"
            assert set(np.asarray(image).ravel()) <= (
                set(range(7)) if name == "classification" else {0, 255}
            )
    document, _ = probe._parse_glb(
        probe._path(case.root, row["artifacts"]["glb"]["path"]).read_bytes()
    )
    assert document["materials"][0]["name"] == "Registered_Generated_Surface"
    assert document["materials"][0]["doubleSided"] is False
    assert document["extras"]["source_age"] == probe.UNKNOWN_AGE
    assert document["extras"]["registered_target_texture"]["target_age_condition"] == 20
    assert document["extras"]["registered_target_texture"]["source_age_label"] is None
    assert row["source_frame"] == document["extras"]["coordinate_metadata"]
    assert not report["service_ready"] and not report["g3_complete"]
    assert not row["texture_metadata"]["original_photo_observation"]
    assert not report["independent_segmentation_ground_truth"]
    probe._verify_descendants(case.root, report)
    assert (case.args.output_dir / "contact.html").is_file()


def test_multiple_conditions_keep_identical_original_geometry_and_common_uv(case):
    first = next(iter(case.jobs.values()))
    second = {**first, "sample_id": "source--sam-045", "target_age": 45}
    case.jobs[second["sample_id"]] = second
    case.records[second["sample_id"]] = case.records[first["sample_id"]].copy()
    case.fits[second["sample_id"]] = case.target
    case.review["target_records"].append(
        {**case.review["target_records"][0], "sample_id": second["sample_id"]}
    )
    case.protocol["expected_generated_images"] = 2
    write_json(case.paths["protocol"], case.protocol)
    case.repin()
    report = probe.run(case.args)
    assert report["summary"]["requested_targets"] == 2
    assert len(report["source_geometry_invariants"]) == 1
    assert (
        report["records"][0]["source_positions_sha256"]
        == report["records"][1]["source_positions_sha256"]
    )
    assert report["records"][0]["gltf_uv_sha256"] == report["records"][1]["gltf_uv_sha256"]


@pytest.mark.parametrize(
    "failure", ["registration", "missing_target", "missing_source", "source_geometry"]
)
def test_failed_requests_and_prior_fit_failures_remain_in_denominator(case, monkeypatch, failure):
    if failure in ("registration", "source_geometry"):

        def fail(*args, **kwargs):
            raise ValueError("Synthetic registration rejection")

        monkeypatch.setattr(
            probe,
            "register_generated_texture" if failure == "registration" else "build_static_mesh",
            fail,
        )
    else:
        case.fits.pop(next(iter(case.jobs)) if failure == "missing_target" else "source")
    report = probe.run(case.args)
    assert report["summary"]["requested_targets"] == 1
    assert report["summary"]["statuses"] == {"failed": 1}
    assert not report["summary"]["all_successful_glb_arrays_and_rgba_roundtripped"]
    assert not report["summary"]["all_requested_glb_roundtrips_passed"]
    assert len(report["retained_prior_fit_failures"]) == 2
    assert "artifacts" not in report["records"][0]
    if failure == "source_geometry":
        assert report["records"][0]["error_code"] == "SOURCE_STATIC_GEOMETRY_FAILED"


def test_later_source_geometry_failure_preserves_completed_targets(case, monkeypatch):
    first = next(iter(case.jobs.values()))
    second = {**first, "sample_id": "second--sam-020", "reference_source_id": "second"}
    case.jobs[second["sample_id"]] = second
    case.records[second["sample_id"]] = case.records[first["sample_id"]].copy()
    second_source = replace(case.source, vertices=case.source.vertices.copy())
    case.fits["second"] = second_source
    case.fits[second["sample_id"]] = case.target
    case.review["target_records"].append(
        {**case.review["target_records"][0], "sample_id": second["sample_id"]}
    )
    case.protocol.update(expected_generated_images=2, expected_source_images=2)
    write_json(case.paths["protocol"], case.protocol)
    case.repin()
    original = probe.build_static_mesh

    def build(source, age):
        if source is second_source:
            raise ValueError("Synthetic second source failure")
        return original(source, age)

    monkeypatch.setattr(probe, "build_static_mesh", build)
    report = probe.run(case.args)
    assert report["summary"]["statuses"] == {"ok": 1, "failed": 1}
    assert report["summary"]["all_successful_glb_arrays_and_rgba_roundtripped"]
    assert not report["summary"]["all_requested_glb_roundtrips_passed"]
    assert report["records"][1]["error_code"] == "SOURCE_STATIC_GEOMETRY_FAILED"
    for pin in report["records"][0]["artifacts"].values():
        assert probe._path(case.root, pin["path"]).is_file()


@pytest.mark.parametrize("notes", ["Reviewed conservative support", ["Reviewed", "Candidate only"]])
def test_mask_review_preserves_string_or_list_notes(case, notes):
    case.review["target_records"][0]["notes"] = notes
    masks = probe.validate_mask_review(case.root, case.review, case.jobs, case.records)
    assert masks[next(iter(case.jobs))][0]["notes"] == notes


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "duplicate",
        "input",
        "fit",
        "count",
        "notes",
        "reviewer",
        "overlap",
        "rgb",
        "nonbinary",
    ],
)
def test_mask_review_rejects_wrong_target_or_unsupported_masks(case, failure):
    row = case.review["target_records"][0]
    if failure == "missing":
        case.review["target_records"].clear()
    elif failure == "duplicate":
        case.review["target_records"].append(row.copy())
    elif failure == "input":
        row["input"] = {**row["input"], "sha256": "0" * 64}
    elif failure == "fit":
        row["target_fit"] = probe._pin(case.root, case.paths["bfm"])
    elif failure == "count":
        row["allowed_pixels"] = 255
    elif failure == "notes":
        row["notes"] = [""]
    elif failure == "reviewer":
        row["reviewer"] = "unreviewed"
    elif failure == "overlap":
        path = case.root / row["occluded_mask"]["path"]
        Image.fromarray(np.full((16, 16), 255, dtype=np.uint8)).save(path)
        row["occluded_mask"] = probe._pin(case.root, path)
        row["excluded_occluder_pixels"] = 256
    else:
        path = case.root / row["allowed_mask"]["path"]
        pixels = np.full((16, 16, 3) if failure == "rgb" else (16, 16), 128, dtype=np.uint8)
        Image.fromarray(pixels).save(path)
        row["allowed_mask"] = probe._pin(case.root, path)
    with pytest.raises(ValueError):
        probe.validate_mask_review(case.root, case.review, case.jobs, case.records)


@pytest.mark.parametrize(
    "failure", ["tamper", "unbound", "selection", "uv_order", "topology", "cohort", "bfm"]
)
def test_input_pins_uv_binding_static_fallback_and_complete_cohort_are_required(case, failure):
    if failure == "tamper":
        with case.paths["protocol_manifest"].open("ab") as stream:
            stream.write(b" ")
    elif failure == "unbound":
        other = case.root / "other-protocol.json"
        other.write_bytes(case.paths["protocol"].read_bytes())
        case.args.protocol = other
    elif failure == "selection":
        write_json(
            case.paths["selection"],
            {"research_route_choice": "sam_difference", "production_route_selected": None},
        )
        case.repin()
    elif failure == "uv_order":
        np.savez_compressed(
            case.paths["uv"], uv=case.uv[::-1], topology_sha256=case.source.topology_sha256
        )
        case.repin()  # An updated plan cannot override the independently supplied UV hash.
    elif failure == "topology":
        case.fits["source"] = replace(case.source, topology_sha256="cd" * 32)
    elif failure == "cohort":
        case.protocol["expected_generated_images"] = 2
        write_json(case.paths["protocol"], case.protocol)
        case.repin()
    else:
        case.generated["expression_basis"]["asset"]["sha256"] = "0" * 64
        write_json(case.paths["generated_report"], case.generated)
        case.repin()
    with pytest.raises(ValueError):
        probe.load_inputs(case.args)
    assert not case.args.output_dir.exists()


def test_existing_output_is_rejected_without_touching_evidence(case, monkeypatch):
    case.args.output_dir.mkdir()
    sentinel = case.args.output_dir / "existing.txt"
    sentinel.write_bytes(b"preserve")

    def forbidden(*args):
        pytest.fail("Existing evidence must be rejected before loading inputs")

    monkeypatch.setattr(probe, "load_inputs", forbidden)
    assert probe.main(["--root", str(case.root), "--output-dir", "new-output"]) == 1
    assert sentinel.read_bytes() == b"preserve"


@pytest.mark.parametrize("failure", ["position", "indices", "uv", "png", "external", "sampler"])
def test_roundtrip_detects_geometry_backface_uv_texture_and_transport_tampering(case, failure):
    texture = probe.register_generated_texture(
        np.zeros((16, 16, 3), dtype=np.uint8),
        case.target,
        case.uv,
        np.ones((16, 16), dtype=bool),
        atlas_size=4,
    )
    base = probe.build_static_mesh(case.source, probe.UNKNOWN_AGE)
    research = {"kind": "sam_generated_registered_uv"}
    extras = probe._parse_glb(base.glb)[0]["extras"]
    extras["registered_target_texture"] = research
    glb = probe._encode_glb(base.vertices, base.normals, base.triangles, extras, texture)
    document, binary = probe._parse_glb(glb)
    if failure in ("position", "indices", "uv"):
        primitive = document["meshes"][0]["primitives"][0]
        accessor_id = (
            primitive["indices"]
            if failure == "indices"
            else primitive["attributes"]["POSITION" if failure == "position" else "TEXCOORD_0"]
        )
        accessor = document["accessors"][accessor_id]
        offset = document["bufferViews"][accessor["bufferView"]]["byteOffset"]
        binary = bytearray(binary)
        if failure == "indices":
            binary[offset : offset + 12] = struct.pack("<III", 0, 1, 2)
        else:
            struct.pack_into("<f", binary, offset, 0.123456)
    elif failure == "png":
        binary = bytearray(binary)
        view = document["bufferViews"][document["images"][0]["bufferView"]]
        binary[view["byteOffset"] + 8] ^= 1
    elif failure == "external":
        document["images"][0]["uri"] = "https://invalid.example/texture.png"
    else:
        document["samplers"][0]["wrapS"] = 10497
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    changed = (
        struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
        + struct.pack("<I4s", len(encoded), b"JSON")
        + encoded
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    with pytest.raises(ValueError):
        probe.verify_glb(changed, base, texture, research)


def test_truncated_glb_is_a_validation_error():
    with pytest.raises(ValueError, match="Truncated"):
        probe._parse_glb(b"glTF")
    data = struct.pack("<4sIII4s", b"glTF", 2, 32, 4000, b"JSON") + b" " * 12
    with pytest.raises(ValueError, match="header"):
        probe._parse_glb(data)


def test_zero_eligible_pixels_preserve_unknown_rgba_without_occlusion_accuracy_claim(case):
    allowed = case.root / case.review["target_records"][0]["allowed_mask"]["path"]
    Image.fromarray(np.zeros((16, 16), dtype=np.uint8)).save(allowed)
    row = case.review["target_records"][0]
    row.update(allowed_mask=probe._pin(case.root, allowed), allowed_pixels=0)
    case.repin()
    report = probe.run(case.args)
    result = report["records"][0]
    assert result["status"] == "ok"
    with Image.open(
        io.BytesIO(probe._path(case.root, result["artifacts"]["atlas"]["path"]).read_bytes())
    ) as image:
        assert np.all(np.asarray(image) == 0)
    assert result["boundary_diagnostics"]["unknown_rgba_zero"]
    assert not result["texture_metadata"]["mask_rejection_is_external_occlusion_measurement"]
    assert not report["age_texture_quality_accepted"]
