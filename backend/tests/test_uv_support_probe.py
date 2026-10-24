"""Synthetic correspondence and integrity counterexamples; no research assets or inference."""

import hashlib
import importlib.util
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from agemorph3d.age_geometry import source_frame
from agemorph3d.tddfa import TddfaResult, project_vertices

_PATH = Path(__file__).resolve().parents[2] / "tools/uv_support_probe.py"
_SPEC = importlib.util.spec_from_file_location("uv_support_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


@pytest.fixture
def triangle():
    raw = TddfaResult(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=np.array([[2, 115, 0], [10, 115, 0], [2, 107, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int64),
        projection=np.eye(3, 4, dtype=np.float32),
        roi=(0.0, 0.0, 120.0, 120.0),
        topology_sha256="ab" * 32,
    )
    uv = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float32)
    allowed = np.ones((16, 16), dtype=bool)
    occluded = np.zeros_like(allowed)
    landmarks = np.zeros((68, 3), dtype=np.float64)
    landmarks[:3, :2] = [[0, 0], [16, 0], [0, 16]]
    return raw, uv, allowed, occluded, landmarks


def trace(case, *, raw=None, allowed=None, occluded=None, saved=None, source=None, frame=None):
    original, uv, eligible, candidate, landmarks = case
    raw = original if raw is None else raw
    source = original.vertices if source is None else source
    return probe.trace_support(
        raw,
        uv,
        eligible if allowed is None else allowed,
        candidate if occluded is None else occluded,
        landmarks[:, :2],
        source,
        source_frame(source) if frame is None else frame,
        saved,
        raster=probe.prepare_uv(uv, raw.triangles, size=4),
        regions={"face": [0, 1, 2]},
    )


def saved_triangle():
    yy, xx = np.mgrid[:4, :4]
    coverage = xx + yy <= 3
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[coverage, 3] = 255
    return {
        "rgba": rgba,
        "classification": np.where(coverage, 6, 0).astype(np.uint8),
        "coverage": coverage,
        "gltf_uv": np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32),
    }


def npz_bytes(**arrays):
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    return stream.getvalue()


def pin(path, root):
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_target_camera_changes_target_xy_but_preserves_source_canonical(triangle):
    raw = triangle[0]
    baseline = trace(triangle)
    projection = raw.projection.copy()
    projection[0, 3] = 2
    shifted = trace(triangle, raw=replace(raw, projection=projection))
    np.testing.assert_allclose(baseline["target_xyz"][0], [2, 6, 0])
    np.testing.assert_allclose(shifted["target_xyz"][0], [4, 6, 0])
    np.testing.assert_array_equal(shifted["source_canonical_xyz"], baseline["source_canonical_xyz"])
    # Native UV owner uses weights (.75,.125,.125), and the original source bbox has height8.
    np.testing.assert_allclose(baseline["barycentric"][0], [0.75, 0.125, 0.125])
    np.testing.assert_allclose(baseline["source_canonical_xyz"][0], [-0.375, 0.375, 0])
    assert baseline["face_owner"][0] == 0


def test_target_shape_is_never_used_to_renormalize_the_source_frame(triangle):
    raw = triangle[0]
    changed = raw.vertices.copy()
    changed[:, 0] += 1
    changed[:, 1] = 115 + (changed[:, 1] - 115) * 0.5
    result = trace(triangle, raw=replace(raw, vertices=changed))
    np.testing.assert_allclose(result["target_xyz"][0], [3, 5.5, 0])
    np.testing.assert_allclose(result["source_canonical_xyz"][0], [-0.375, 0.375, 0])


def test_prepare_uv_flips_once_in_float64_before_saved_float32_quantization(triangle):
    _, uv, *_ = triangle
    uv = uv.copy()
    uv[0, 1] = np.float32(1e-8)
    top_left, *_ = probe.prepare_uv(uv, triangle[0].triangles, size=4)
    assert top_left.dtype == np.float64
    assert top_left[0, 1] == 1.0 - float(uv[0, 1])
    assert top_left[0, 1] != float(top_left.astype(np.float32)[0, 1])
    np.testing.assert_array_equal(uv[1:], [[1, 1], [0, 0]])


@pytest.mark.parametrize("mode,reason", [("back", 2), ("outside", 3), ("mask", 5)])
def test_rejection_partition_keeps_non_supported_texels_in_global_denominator(
    triangle, mode, reason
):
    raw = triangle[0]
    if mode == "back":
        result = trace(triangle, raw=replace(raw, triangles=raw.triangles[:, ::-1]))
    elif mode == "outside":
        projection = raw.projection.copy()
        projection[0, 3] = 100
        result = trace(triangle, raw=replace(raw, projection=projection))
    else:
        result = trace(triangle, allowed=np.zeros_like(triangle[2]))
    assert np.count_nonzero(result["classification"] == reason) == 10
    assert np.count_nonzero(result["classification"] == 0) == 6
    assert not result["coverage"].any()
    assert result["classification"].size == 16


def test_native_uv_triangle_winding_is_not_replaced_by_exported_glb_winding(triangle):
    forward = trace(triangle)
    raw = triangle[0]
    backward = trace(triangle, raw=replace(raw, triangles=raw.triangles[:, [0, 2, 1]]))
    assert np.count_nonzero(forward["classification"] == 6) == 10
    assert np.count_nonzero(backward["classification"] == 2) == 10


def test_ambiguous_overlapping_uv_interiors_remain_unknown(triangle):
    raw, uv, allowed, occluded, landmarks = triangle
    raw = replace(
        raw,
        vertices=np.concatenate([raw.vertices, raw.vertices]),
        triangles=np.array([[0, 1, 2], [3, 4, 5]]),
    )
    uv = np.concatenate([uv, uv])
    case = raw, uv, allowed, occluded, landmarks
    result = trace(case)
    assert np.count_nonzero(result["classification"] == 1) == 6
    assert np.count_nonzero(result["classification"] == 6) == 4
    assert len(result["texel_rows_columns"]) == 4


def test_continuous_depth_rejects_far_surface_even_when_its_mask_allows(triangle):
    raw, _, allowed, occluded, landmarks = triangle
    raw = replace(
        raw,
        vertices=np.concatenate([raw.vertices, raw.vertices + [0, 0, 10]]).astype(np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]]),
    )
    uv = np.array([[0, 1], [0.5, 1], [0, 0], [0.5, 1], [1, 1], [1, 0]], np.float32)
    result = trace((raw, uv, allowed, occluded, landmarks))
    assert np.count_nonzero(result["classification"] == 4) > 0
    assert np.count_nonzero(result["classification"] == 6) > 0
    assert not np.any(result["coverage"][:, :2])


def test_bilinear_partition_distinguishes_occluder_other_and_mixed_contributors():
    allowed = np.zeros((2, 2), dtype=bool)
    allowed[0, 0] = True
    occluded = np.array([[False, True], [False, False]])
    xy = np.array([[0, 0], [0.5, 0], [0, 0.5], [0.5, 0.5]], dtype=np.float64)
    np.testing.assert_array_equal(
        probe.mask_rejection_partition(allowed, occluded, xy), [0, 1, 2, 3]
    )


def test_zero_weight_mask_neighbours_and_clamped_image_edge_do_not_reject():
    allowed = np.zeros((2, 2), dtype=bool)
    allowed[1, 1] = True
    occluded = np.zeros_like(allowed)
    np.testing.assert_array_equal(
        probe.mask_rejection_partition(allowed, occluded, np.array([[1.0, 1.0]])), [0]
    )


@pytest.mark.parametrize(
    "xy", [np.array([[-0.001, 0]]), np.array([[2, 0]]), np.array([[np.nan, 0]])]
)
def test_mask_partition_rejects_nonfinite_or_outside_queries(xy):
    with pytest.raises(ValueError):
        probe.mask_rejection_partition(np.ones((2, 2), bool), np.zeros((2, 2), bool), xy)


def test_allowed_and_reviewed_occluder_overlap_is_invalid():
    with pytest.raises(ValueError):
        probe.mask_rejection_partition(
            np.ones((2, 2), bool), np.ones((2, 2), bool), np.array([[0.0, 0.0]])
        )


def test_region_boxes_use_declared_padding_half_open_edges_and_overlapping_bits():
    landmarks = np.zeros((68, 3), dtype=float)
    landmarks[:4, :2] = [[2, 4], [6, 8], [3, 5], [7, 9]]
    xy = np.array([[1, 3], [7, 9], [6.999, 8.999], [4, 6], [np.nextafter(1, 0), 3]])
    bits, boxes = probe.region_membership(
        xy, landmarks[:, :2], regions={"first": [0, 1], "second": [2, 3]}, padding=0.25
    )
    np.testing.assert_array_equal(bits, [1, 2, 3, 3, 0])
    assert set(boxes) == {"first", "second"}


def test_region_membership_rejects_degenerate_fit_instead_of_inventing_size():
    landmarks = np.ones((68, 3), dtype=float)
    landmarks[1, 1] = 2
    with pytest.raises(ValueError):
        probe.region_membership(
            np.array([[1, 1]], dtype=float),
            landmarks[:, :2],
            regions={"collapsed": [0, 1]},
        )


def test_saved_sampling_schema_and_global_counts_are_checked_against_actual_correspondence(
    triangle,
):
    result = trace(triangle, saved=saved_triangle())
    np.testing.assert_array_equal(result["classification"], saved_triangle()["classification"])
    assert sum(np.count_nonzero(result["classification"] == code) for code in range(7)) == 16
    counts = result["counts"]["all_unique_correspondence"]
    assert counts["requested"] == 10
    assert sum(counts["classification_counts"].values()) == 10


def test_region_counts_preserve_zero_denominator_and_do_not_turn_overlaps_into_global_counts():
    classification = np.array([[6, 5], [3, 4]], dtype=np.uint8)
    texels = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
    result = probe.region_counts(
        classification,
        texels,
        np.array([1, 3, 2, 0], dtype=np.uint8),
        np.array([0, 1, 0, 0], dtype=np.uint8),
        region_names=("first", "second", "absent"),
    )
    assert result["all_unique_correspondence"]["requested"] == 4
    assert result["all_unique_correspondence"]["support"] == 0.25
    assert result["first"]["requested"] == 2
    assert result["first"]["support"] == 0.5
    assert result["second"]["requested"] == 2
    assert result["second"]["support"] == 0
    assert result["absent"]["requested"] == 0
    assert result["absent"]["support"] is None
    for row in result.values():
        assert sum(row["classification_counts"].values()) == row["requested"]


@pytest.mark.parametrize("corruption", ["unknown_rgb", "wrong_alpha", "wrong_class", "extra_array"])
def test_saved_sampling_corruption_cannot_be_accepted(triangle, corruption):
    saved = saved_triangle()
    if corruption == "unknown_rgb":
        saved["rgba"][3, 3, 0] = 1
    elif corruption == "wrong_alpha":
        saved["rgba"][0, 0, 3] = 0
    elif corruption == "wrong_class":
        saved["classification"][0, 0] = 4
    else:
        saved["owner"] = np.zeros((4, 4), dtype=int)
    with pytest.raises(ValueError):
        trace(triangle, saved=saved)


def test_source_transform_drift_is_rejected(triangle):
    raw = triangle[0]
    minimal = source_frame(raw.vertices)
    frame = {
        **minimal,
        "source_bbox_height": 8.0,
        "source_topology_sha256": raw.topology_sha256,
        "vertex_order_preserved": True,
        "face_order_preserved": True,
        "winding": "source_face_a_b_c_to_a_c_b",
        "axis_rotation_row_major": np.eye(3).reshape(-1).tolist(),
        "source_projection_row_major": raw.projection.reshape(-1).tolist(),
        "source_roi": list(raw.roi),
    }
    probe._source_frame(raw, frame, {"canonical_frame": minimal})
    frame["source_to_canonical_uniform_scale"] *= 2
    with pytest.raises(ValueError):
        probe._source_frame(raw, frame, {"canonical_frame": minimal})


@pytest.mark.parametrize("corruption", ["uv_nan", "face_oob", "duplicate_index"])
def test_uv_raster_input_guards(triangle, corruption):
    uv, faces = triangle[1].copy(), triangle[0].triangles.copy()
    if corruption == "uv_nan":
        uv[0, 0] = np.nan
    elif corruption == "face_oob":
        faces[0, 2] = 3
    else:
        faces[0, 2] = 0
    with pytest.raises(ValueError):
        probe.prepare_uv(uv, faces, size=4)


def test_safe_npz_accepts_only_declared_numeric_arrays():
    data = npz_bytes(shape=np.arange(40, dtype=np.float32))
    np.testing.assert_array_equal(probe.safe_npz(data, ("shape",))["shape"], np.arange(40))
    with pytest.raises(ValueError):
        probe.safe_npz(data, ("different",))


def test_safe_npz_does_not_deserialize_object_arrays():
    with pytest.raises(ValueError):
        probe.safe_npz(
            npz_bytes(shape=np.array([{"secret": "synthetic"}] * 40, dtype=object)), ("shape",)
        )


def test_safe_npz_rejects_duplicate_archive_members():
    inner = io.BytesIO()
    np.save(inner, np.arange(40, dtype=np.float32), allow_pickle=False)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("shape.npy", inner.getvalue())
        with pytest.warns(UserWarning, match="Duplicate"):
            zipped.writestr("shape.npy", inner.getvalue())
    with pytest.raises(ValueError):
        probe.safe_npz(archive.getvalue(), ("shape",))


def test_safe_npz_rejects_oversize_header_before_numpy_decoding(monkeypatch):
    inner = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        inner, {"descr": "<f4", "fortran_order": False, "shape": (10_000_000, 3)}
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("vertices.npy", inner.getvalue())

    def forbidden_decode(*args, **kwargs):
        pytest.fail("An oversized array header must fail before NumPy allocates or decodes it.")

    monkeypatch.setattr(probe.np, "load", forbidden_decode)
    with pytest.raises(ValueError):
        probe.safe_npz(archive.getvalue(), ("vertices",))


def test_safe_npz_expanded_budget_is_enforced_before_decoding(monkeypatch):
    data = npz_bytes(shape=np.arange(40, dtype=np.float32))
    monkeypatch.setattr(probe, "UNPACKED_LIMIT", 64)

    def forbidden_decode(*args, **kwargs):
        pytest.fail("The expanded ZIP budget must be checked before decoding.")

    monkeypatch.setattr(probe.np, "load", forbidden_decode)
    with pytest.raises(ValueError):
        probe.safe_npz(data, ("shape",))


def test_frozen_input_bytes_are_verified_and_post_read_drift_is_detected(tmp_path):
    path = tmp_path / "input.json"
    path.write_bytes(b'{"state":"first"}')
    frozen_pin = pin(path, tmp_path)
    inputs = probe.Inputs(tmp_path, [frozen_pin])
    assert inputs.read(frozen_pin) == b'{"state":"first"}'
    path.write_bytes(b'{"state":"later"}')
    with pytest.raises(ValueError):
        inputs.recheck()


def test_freeze_rejects_reassigned_pin_and_enforces_byte_budget(tmp_path):
    path = tmp_path / "input.json"
    path.write_bytes(b"synthetic content")
    frozen_pin = pin(path, tmp_path)
    inputs = probe.Inputs(tmp_path, [frozen_pin])
    changed_pin = {**frozen_pin, "sha256": "00" * 32}
    with pytest.raises(ValueError):
        inputs.read(changed_pin)
    with pytest.raises(ValueError):
        inputs.read(frozen_pin, max_bytes=1)


def test_frozen_input_cannot_escape_project_root(tmp_path):
    frozen_pin = {"path": "../outside.json", "bytes": 1, "sha256": "00" * 32}
    with pytest.raises(ValueError):
        probe.Inputs(tmp_path, [frozen_pin]).read(frozen_pin)


def test_output_refuses_overwrite_and_requires_existing_ignore_rule(tmp_path):
    (tmp_path / ".gitignore").write_text("output/\n", encoding="utf-8")
    previous = tmp_path / "output/research/previous"
    previous.mkdir(parents=True)
    sentinel = previous / "report.json"
    sentinel.write_text("original evidence", encoding="utf-8")
    with pytest.raises(ValueError):
        probe._output_path(tmp_path, previous)
    assert sentinel.read_text(encoding="utf-8") == "original evidence"
    with pytest.raises(ValueError):
        probe._output_path(tmp_path, tmp_path / "elsewhere")
    (tmp_path / ".gitignore").write_text("output/\n!output/\n", encoding="utf-8")
    with pytest.raises(ValueError):
        probe._output_path(tmp_path, tmp_path / "output/research/new")


@pytest.fixture
def cohort_metadata():
    protocol = json.loads(
        (_PATH.parents[1] / "docs/uv-support-v1.json").read_text(encoding="utf-8")
    )
    n0, registration, generated, reset = (
        {"bridge_cases": [], "adult_images": []},
        {"records": []},
        {"fit_records": []},
        {"records": []},
    )

    def synthetic_pin(name):
        return {"path": name, "bytes": 1, "sha256": hashlib.sha256(name.encode()).hexdigest()}

    cohort = {
        "fgnet-004a63": [20, 45, 63, 70],
        "fgnet-082a27": [20, 27, 45, 70],
        "fgnet-006a55": [20, 45, 55, 70],
    }
    for source_id, ages in cohort.items():
        label = int(source_id[-2:])
        image, source_fit = synthetic_pin(source_id + ".png"), synthetic_pin(source_id + ".npz")
        research_age = {"value": label, "method": "filename_research_label"}
        frame = {"synthetic_source_frame": source_id}
        case = {
            "sample_id": source_id,
            "subject_id": source_id,
            "group": "development",
            "source_status": "passed",
            "source_age": research_age,
            "source": image,
            "target_runs": [],
        }
        source = {
            "sample_id": source_id,
            "subject_id": source_id,
            "group": "development",
            "status": "ok",
            "source_age": dict(probe.UNKNOWN_AGE),
            "input": image,
            "label_source_age": label,
            "research_source_age": research_age,
            "fit_artifact": source_fit,
            "source_frame": frame,
        }
        original_fit = {
            "sample_id": source_id,
            "subject_id": source_id,
            "input": image,
            "role": "original",
            "status": "ok",
            "reference_source_id": source_id,
            "source_age": label,
            "fit_artifact": source_fit,
        }
        n0["bridge_cases"].append(case)
        generated["fit_records"].append(original_fit)
        reset["records"].append(source)
        for age in ages:
            sample_id = f"{source_id}--sam-{age:03d}"
            image, target_fit = synthetic_pin(sample_id + ".png"), synthetic_pin(sample_id + ".npz")
            if age == label:
                case["same_age_control"] = {
                    "status": "generated",
                    "target_age": age,
                    "output": image,
                }
            else:
                case["target_runs"].append({**image, "target_age": age})
            review = {
                "sample_id": sample_id,
                "input": image,
                "target_fit": target_fit,
                "status": "reviewed_conservative_exclusion",
                "reviewer": "codex_visual_review",
                "automatic_external_occlusion_detection": False,
                "independent_mask_ground_truth": False,
            }
            registration["records"].append(
                {
                    "sample_id": sample_id,
                    "source_id": source_id,
                    "target_age": age,
                    "subject_id": source_id,
                    "source_age_label": label,
                    "input": image,
                    "status": "ok",
                    "source_age": dict(probe.UNKNOWN_AGE),
                    "asset_mode": "static",
                    "capabilities": {"age_morph": False, "age_texture": False},
                    "source_frame": frame,
                    "target_fit": target_fit,
                    "mask_review": review,
                    "sampling_geometry": "target_full_identity_expression_raw_fit",
                }
            )
            generated["fit_records"].append(
                {
                    "sample_id": sample_id,
                    "input": image,
                    "fit_artifact": target_fit,
                    "status": "ok",
                    "role": "sam_generated",
                    "subject_id": source_id,
                    "source_age": label,
                    "reference_source_id": source_id,
                    "target_age": age,
                }
            )
    return protocol, n0, registration, generated, reset


def test_selected_cohort_keeps_every_condition_and_unknown_api_age(cohort_metadata):
    rows = probe.select_targets(*cohort_metadata)
    assert len(rows) == 12
    assert len({row["registration"]["source_id"] for row in rows}) == 3
    assert all(row["registration"]["source_age"]["value"] is None for row in rows)


@pytest.mark.parametrize(
    "corruption", ["missing_condition", "holdout", "default_age", "quality_flag"]
)
def test_selected_cohort_rejects_missing_conditions_or_promoted_claims(cohort_metadata, corruption):
    protocol, n0, registration, _, _ = cohort_metadata
    if corruption == "missing_condition":
        n0["bridge_cases"][0]["target_runs"].pop()
    elif corruption == "holdout":
        n0["bridge_cases"][0]["group"] = "holdout"
    elif corruption == "default_age":
        registration["records"][0]["source_age"]["value"] = 35
    else:
        protocol["flags"]["identity_quality_accepted"] = True
    with pytest.raises(ValueError):
        probe.select_targets(*cohort_metadata)


def test_noncontiguous_landmark_triplets_preserve_xy_and_have_independent_depth_shifts(triangle):
    # A sparse point combines X/Z from vertex0 and Y from vertex2; it is not vertex0.
    raw = triangle[0]
    vertices = raw.vertices.copy()
    vertices[:, 2] = [5, 20, 10]
    raw = replace(raw, vertices=vertices)
    coordinates = np.tile([0, 7, 2], (68, 1))
    sparse = project_vertices(raw, coordinates)
    np.testing.assert_array_equal(sparse[:, :2], np.tile([1, 13], (68, 1)))
    np.testing.assert_array_equal(sparse[:, 2], np.zeros(68))
    dense = project_vertices(raw)
    assert dense[1, 2] != sparse[1, 2]
