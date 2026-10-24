"""Synthetic historical-mask candidate boundaries; no real asset decoding or inference."""

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools/mask_replay_probe.py"
_SPEC = importlib.util.spec_from_file_location("mask_replay_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


@pytest.fixture
def landmarks():
    points = np.full((68, 2), 32.0, dtype=np.float64)
    points[:4] = [[8, 8], [55, 8], [55, 55], [8, 55]]
    points[60:68] = [[28, 28], [35, 28], [35, 35], [28, 35]] * 2
    return points


def band(width=64, y0=25, y1=45):
    return {
        "kind": "glasses_candidate_band",
        "x0": 0,
        "x1_exclusive": width,
        "y0": y0,
        "y1_exclusive": y1,
    }


def test_recipe_layers_have_independently_known_rectangle_areas(landmarks):
    before = landmarks.copy()
    result = probe.construct_masks(landmarks, 64, 64, [])
    assert int(result["H"].sum()) == 48 * 48
    assert int(result["E"].sum()) == 40 * 40
    assert int(result["M"].sum()) == 14 * 14
    assert int(result["base"].sum()) == 1404
    assert int(result["allowed"].sum()) == 1404
    assert not result["B"].any() and not result["occluded"].any()
    assert result["reason"][0, 0] == 1
    assert result["reason"][20, 8] == 2
    assert result["reason"][30, 30] == 3
    assert result["reason"][20, 20] == 0
    assert sum(np.count_nonzero(result["reason"] == code) for code in range(5)) == 4096
    for name in ("H", "E", "M", "B", "base", "allowed", "occluded"):
        assert result[name].dtype == bool and result[name].shape == (64, 64)
    np.testing.assert_array_equal(landmarks, before)


def test_half_integer_polygon_coordinates_use_bankers_rounding(landmarks):
    landmarks[:4] = [[8.5, 8.5], [55.5, 8.5], [55.5, 55.5], [8.5, 55.5]]
    result = probe.construct_masks(landmarks, 64, 64, [])
    assert result["H"][8, 8]
    assert result["H"][56, 56]
    assert not result["H"][57, 57]
    assert int(result["H"].sum()) == 49 * 49


def test_erosion_constant_255_preserves_a_face_touching_the_image_border(landmarks):
    landmarks[:4] = [[0, 0], [63, 0], [63, 63], [0, 63]]
    result = probe.construct_masks(landmarks, 64, 64, [])
    assert result["H"].all() and result["E"].all()
    assert result["E"][0, 0] and result["E"][63, 63]


def test_mouth_dilation_border_zero_never_paints_the_opposite_image_edge(landmarks):
    landmarks[60:68] = [[0, 0], [3, 0], [3, 3], [0, 3]] * 2
    result = probe.construct_masks(landmarks, 64, 64, [])
    assert result["M"][6, 6]
    assert not result["M"][7, 0]
    assert not result["M"][63, 63]
    assert int(result["M"].sum()) == 49


def test_outside_polygon_vertices_are_raster_clipped_without_clamping_vertices(landmarks):
    landmarks[:4] = [[-2, -2], [55, -2], [55, 55], [-2, 55]]
    result = probe.construct_masks(landmarks, 64, 64, [])
    assert result["H"][0, 0] and result["E"][0, 0]
    assert not result["H"][:, 56:].any()
    assert not result["H"][56:].any()
    assert int(result["H"].sum()) == 56 * 56


def test_mouth_and_erosion_priority_precede_the_reviewed_band(landmarks):
    result = probe.construct_masks(landmarks, 64, 64, [band()])
    assert result["reason"][30, 0] == 1
    assert result["reason"][30, 8] == 2
    assert result["reason"][30, 30] == 3
    assert result["reason"][30, 20] == 4
    assert result["reason"][20, 20] == 0
    assert not result["occluded"][30, 30]
    assert result["occluded"][30, 20]
    assert not np.any(result["allowed"] & result["occluded"])
    np.testing.assert_array_equal(result["allowed"] | result["occluded"], result["base"])


def test_rectangles_are_half_open_and_overlaps_form_a_union(landmarks):
    result = probe.construct_masks(landmarks, 64, 64, [band(y0=20, y1=30), band(y0=25, y1=35)])
    assert not result["B"][19].any()
    assert result["B"][20:35].all()
    assert not result["B"][35].any()
    assert int(result["B"].sum()) == 64 * 15


@pytest.mark.parametrize("value", [np.nan, np.inf, 2**31 + 100.0, -(2**31) - 100.0])
def test_nonfinite_or_int32_overflow_landmarks_fail_before_rasterization(landmarks, value):
    landmarks[0, 0] = value
    with pytest.raises(ValueError):
        probe.construct_masks(landmarks, 64, 64, [])


@pytest.mark.parametrize("part", ["H", "M", "rounded_H"])
def test_integer_degenerate_hulls_do_not_receive_an_invented_mask(landmarks, part):
    if part == "H":
        landmarks[:27] = [20, 20]
    elif part == "M":
        landmarks[60:68] = [30, 30]
    else:
        landmarks[:27] = [20.1, 20.1]
        landmarks[:3] = [[20.1, 20.1], [20.4, 20.1], [20.1, 20.4]]
    with pytest.raises(ValueError):
        probe.construct_masks(landmarks, 64, 64, [])


@pytest.mark.parametrize("dimensions", [(0, 64), (64, 0), (True, 64), (64.0, 64), (5000, 5000)])
def test_invalid_image_dimensions_are_rejected_before_allocating(landmarks, dimensions):
    with pytest.raises(ValueError):
        probe.construct_masks(landmarks, *dimensions, [])


@pytest.mark.parametrize("shape", [(67, 2), (68, 3), (136,)])
def test_constructor_requires_exactly_68_continuous_xy_points(shape):
    with pytest.raises(ValueError):
        probe.construct_masks(np.zeros(shape), 64, 64, [])


@pytest.mark.parametrize(
    "change", ["negative", "oversized", "reversed", "fractional", "unknown", "extra"]
)
def test_review_rectangles_require_strict_bounded_integer_schema(landmarks, change):
    rectangle = band()
    if change == "negative":
        rectangle["x0"] = -1
    elif change == "oversized":
        rectangle["y1_exclusive"] = 65
    elif change == "reversed":
        rectangle["y1_exclusive"] = rectangle["y0"]
    elif change == "fractional":
        rectangle["y0"] = 25.5
    elif change == "unknown":
        rectangle["kind"] = "invented_occluder"
    else:
        rectangle["confidence"] = 1
    with pytest.raises(ValueError):
        probe.construct_masks(landmarks, 64, 64, [rectangle])


def test_focus_band_uses_floor_of_original_continuous_eyebrow_y(landmarks):
    landmarks[17:27, 1] = 43.6
    # floor43.6-18=25; rounding before floor would incorrectly produce26.
    probe.audit_exclusions("fgnet-004a63--sam-020", landmarks, [band(y0=25, y1=650)], 64, 700)
    with pytest.raises(ValueError):
        probe.audit_exclusions("fgnet-004a63--sam-020", landmarks, [band(y0=26, y1=650)], 64, 700)


@pytest.mark.parametrize("change", ["missing", "double", "end", "x0", "width"])
def test_focus_exclusions_cannot_be_relaxed_or_reassigned(landmarks, change):
    rectangle = band(y0=14, y1=650)
    exclusions = [rectangle]
    if change == "missing":
        exclusions = []
    elif change == "double":
        exclusions = [rectangle, rectangle.copy()]
    elif change == "end":
        rectangle["y1_exclusive"] = 649
    elif change == "x0":
        rectangle["x0"] = 1
    else:
        rectangle["x1_exclusive"] = 63
    with pytest.raises(ValueError):
        probe.audit_exclusions("fgnet-004a63--sam-070", landmarks, exclusions, 64, 700)


@pytest.mark.parametrize("sample_id", ["fgnet-082a27--sam-020", "fgnet-006a55--sam-055"])
def test_comparators_cannot_gain_a_reviewed_exclusion(sample_id, landmarks):
    probe.audit_exclusions(sample_id, landmarks, [], 64, 700)
    with pytest.raises(ValueError):
        probe.audit_exclusions(sample_id, landmarks, [band(y0=14, y1=650)], 64, 700)


def test_pixel_comparison_preserves_added_removed_and_global_gate(landmarks):
    reconstructed = probe.construct_masks(landmarks, 64, 64, [])
    allowed, occluded = reconstructed["allowed"].copy(), reconstructed["occluded"].copy()
    exact = probe.pixel_comparison(reconstructed, allowed, occluded)
    assert exact["exact"] is True
    assert probe.all_masks_match([exact] * 12)
    assert not probe.all_masks_match([exact] * 11)
    allowed[20, 20] = False
    allowed[0, 0] = True
    occluded[1, 1] = True
    changed = probe.pixel_comparison(reconstructed, allowed, occluded)
    assert changed["exact"] is False
    assert changed["allowed"]["xor_mismatch_pixels"] == 2
    assert changed["allowed"]["added_pixels"] == 1
    assert changed["allowed"]["removed_pixels"] == 1
    assert changed["occluded"]["xor_mismatch_pixels"] == 1
    assert changed["occluded"]["removed_pixels"] == 1
    assert not probe.all_masks_match([exact] * 11 + [changed])


def test_zero_weight_contributors_do_not_add_reasons_and_image_edge_is_clamped():
    reason = np.array([[1, 2], [3, 0]], dtype=np.uint8)
    xy = np.array([[1, 1], [0, 0], [0.5, 0], [0, 0.5], [0.5, 0.5]])
    np.testing.assert_array_equal(probe.contributor_bits(reason, xy), [0, 1, 3, 5, 7])


def test_every_strictly_positive_weight_is_preserved_without_an_epsilon():
    reason = np.array([[0, 4], [0, 0]], dtype=np.uint8)
    xy = np.array([[0, 0], [np.nextafter(0.0, 1.0), 0]])
    np.testing.assert_array_equal(probe.contributor_bits(reason, xy), [0, 8])


@pytest.mark.parametrize(
    "xy", [np.array([[-0.001, 0]]), np.array([[2, 0]]), np.array([[np.nan, 0]])]
)
def test_contributor_queries_never_clamp_an_out_of_frame_point_into_support(xy):
    with pytest.raises(ValueError):
        probe.contributor_bits(np.zeros((2, 2), dtype=np.uint8), xy)


def test_contributor_reason_values_are_closed_to_declared_pixel_labels():
    with pytest.raises(ValueError):
        probe.contributor_bits(np.array([[5]], dtype=np.uint8), np.array([[0.0, 0.0]]))


@pytest.fixture
def all_reason_combinations():
    reason = np.zeros((2, 45), dtype=np.uint8)
    xy = []
    for subset in range(1, 16):
        labels = [label for label in range(1, 5) if subset & (1 << (label - 1))]
        patch = np.zeros(4, dtype=np.uint8)
        patch[: len(labels)] = labels
        start = (subset - 1) * 3
        reason[:, start : start + 2] = patch.reshape(2, 2)
        xy.append([start + 0.5, 0.5])
    bits = probe.contributor_bits(reason, np.asarray(xy))
    old_partition = np.array(
        [1 if value == 8 else (3 if value & 8 else 2) for value in range(1, 16)], dtype=np.uint8
    )
    return bits, old_partition


def test_all_15_combinations_are_mutually_exclusive_and_recover_old_three_partitions(
    all_reason_combinations,
):
    bits, old_partition = all_reason_combinations
    np.testing.assert_array_equal(bits, np.arange(1, 16, dtype=np.uint8))
    region_bits = np.full(15, 3, dtype=np.uint8)
    result = probe.decompose_regions(
        bits, old_partition, region_bits, region_names=("first", "second")
    )
    global_row = result["all_unique_correspondence"]
    assert global_row["mask_rejected"] == 15
    assert global_row["combination_counts"] == {str(value): 1 for value in range(1, 16)}
    assert global_row["partition_counts"] == {
        "reviewed_occluder_only": 1,
        "other_ineligible_only": 7,
        "mixed_contributors": 7,
    }
    assert result["first"]["mask_rejected"] == 15
    assert result["second"]["mask_rejected"] == 15


def test_decomposition_keeps_original_requested_denominator_and_zero_regions(
    all_reason_combinations,
):
    bits, old_partition = all_reason_combinations
    expected = {
        "all_unique_correspondence": {
            "requested": 40,
            "classification_counts": {"mask_rejected": 15},
        },
        "first": {"requested": 30, "classification_counts": {"mask_rejected": 15}},
        "empty": {"requested": 0, "classification_counts": {"mask_rejected": 0}},
    }
    for name, row in expected.items():
        row["rejection_counts"] = {
            "reviewed_occluder_only": 0 if name == "empty" else 1,
            "other_ineligible_only": 0 if name == "empty" else 7,
            "mixed_contributors": 0 if name == "empty" else 7,
        }
    result = probe.decompose_regions(
        bits,
        old_partition,
        np.ones(15, dtype=np.uint8),
        region_names=("first", "empty"),
        expected_counts=expected,
    )
    assert result["all_unique_correspondence"]["requested"] == 40
    assert result["first"]["requested"] == 30
    assert result["empty"]["requested"] == 0
    assert result["empty"]["mask_rejected"] == 0
    assert sum(result["empty"]["combination_counts"].values()) == 0


@pytest.mark.parametrize("corruption", ["zero", "above15", "old_mismatch"])
def test_non_class5_or_inconsistent_old_partition_cannot_enter_decomposition(
    all_reason_combinations, corruption
):
    bits, old_partition = (value.copy() for value in all_reason_combinations)
    if corruption == "zero":
        bits[0] = 0
    elif corruption == "above15":
        bits[0] = 16
    else:
        old_partition[0] = 1
    with pytest.raises(ValueError):
        probe.decompose_regions(
            bits, old_partition, np.ones(15, dtype=np.uint8), region_names=("first",)
        )


@pytest.fixture
def vectors():
    return {
        "texel_rows_columns": np.array([[0, 0], [0, 1]], dtype=np.int32),
        "face_owner": np.array([0, 0], dtype=np.int32),
        "barycentric": np.array([[1, 0, 0], [0.75, 0.25, 0]], dtype=np.float64),
        "target_xyz": np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64),
        "source_canonical_xyz": np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64),
        "region_bits": np.array([0, 1], dtype=np.uint8),
        "rejection_partition": np.array([0, 2], dtype=np.uint8),
    }


def archive_bytes(values):
    stream = io.BytesIO()
    np.savez_compressed(stream, **values)
    return stream.getvalue()


def test_seven_vector_archive_has_exact_row_binding(vectors):
    data = archive_bytes(vectors)
    loaded = probe.load_vectors(data, expected_count=2)
    for name, expected in vectors.items():
        np.testing.assert_array_equal(loaded[name], expected)
    with pytest.raises(ValueError):
        probe.load_vectors(data, expected_count=3)


@pytest.mark.parametrize(
    "corruption", ["pickle", "rows", "dtype", "duplicate_texel", "outside_texel", "bary", "nan"]
)
def test_corrupt_vector_archives_cannot_be_used_for_recipe_attribution(vectors, corruption):
    if corruption == "pickle":
        vectors["target_xyz"] = np.full((2, 3), {"synthetic": True}, dtype=object)
    elif corruption == "rows":
        vectors["barycentric"] = vectors["barycentric"][:1]
    elif corruption == "dtype":
        vectors["face_owner"] = vectors["face_owner"].astype(np.uint8)
    elif corruption == "duplicate_texel":
        vectors["texel_rows_columns"][1] = [0, 0]
    elif corruption == "outside_texel":
        vectors["texel_rows_columns"][1] = [0, 256]
    elif corruption == "bary":
        vectors["barycentric"][0] = [0.5, 0, 0]
    else:
        vectors["target_xyz"][0, 0] = np.nan
    with pytest.raises(ValueError):
        probe.load_vectors(archive_bytes(vectors))


def test_vector_row_budget_is_checked_from_headers_before_decoding(vectors, monkeypatch):
    oversized = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        oversized, {"descr": "<f8", "fortran_order": False, "shape": (65537, 3)}
    )
    rewritten = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive_bytes(vectors))) as original:
        with zipfile.ZipFile(rewritten, "w") as archive:
            for name in original.namelist():
                archive.writestr(
                    name, oversized.getvalue() if name == "target_xyz.npy" else original.read(name)
                )

    def forbidden_decode(*args, **kwargs):
        pytest.fail("Invalid vector headers must fail before allocating NumPy arrays.")

    monkeypatch.setattr(probe.np, "load", forbidden_decode)
    with pytest.raises(ValueError):
        probe.load_vectors(rewritten.getvalue())


@pytest.fixture
def mask_protocol():
    return json.loads((_PATH.parents[1] / "docs/mask-replay-v1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("corruption", ["holdout", "default_age", "quality", "historical_identity"])
def test_candidate_protocol_cannot_promote_research_scope(mask_protocol, corruption):
    probe._protocol(mask_protocol)
    if corruption == "holdout":
        mask_protocol["cohort"]["group"] = "holdout"
    elif corruption == "default_age":
        mask_protocol["cohort"]["api_source_age"]["value"] = 35
    elif corruption == "quality":
        mask_protocol["flags"]["identity_quality_accepted"] = True
    else:
        mask_protocol["flags"]["historical_process_identity_proven"] = True
    with pytest.raises(ValueError):
        probe._protocol(mask_protocol)


@pytest.fixture
def fake_run(tmp_path, monkeypatch, mask_protocol):
    """Real input snapshots, synthetic metadata, and a mocked pixel/decomposition boundary."""
    (tmp_path / ".gitignore").write_text("output/\n", encoding="utf-8")
    runtime = {"synthetic_runtime": True}

    def frozen_file(name, content):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    roles = {
        name: frozen_file(
            name + ".json", json.dumps(mask_protocol if name == "protocol" else {}).encode()
        )
        for name in probe.ROLES
    }
    source_pins = [frozen_file(name, b"# synthetic source snapshot\n") for name in probe.SOURCES]
    plan = {
        "schema_version": 1,
        "protocol_id": "agemorph3d-mask-replay-v1",
        "runtime": runtime,
        "roles": roles,
        "inputs": [*roles.values(), *source_pins],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    selected = []
    for source_id, ages in mask_protocol["cohort"]["sources"].items():
        for age in ages:
            selected.append(
                {
                    "registration": {
                        "sample_id": f"{source_id}--sam-{age:03d}",
                        "source_id": source_id,
                        "target_age": age,
                        "source_age_label": int(source_id[-2:]),
                        "mask_review": {"exclusions": []},
                    }
                }
            )
    old_records = {item["registration"]["sample_id"]: {} for item in selected}
    monkeypatch.setattr(probe.uv, "runtime_fingerprint", lambda: runtime)
    monkeypatch.setattr(probe, "derive_input_pins", lambda metadata: [])
    monkeypatch.setattr(probe, "_selected", lambda inputs, roles, metadata: (selected, old_records))
    calls = {"pixels": 0, "decompositions": 0}

    def pixel_record(inputs, item):
        calls["pixels"] += 1
        return {"reason": np.zeros((1, 1), np.uint8), "pixel_counts": {}}, {"exact": True}

    def decomposition(inputs, item, old, reason):
        calls["decompositions"] += 1
        return {"synthetic_decomposition": True}

    monkeypatch.setattr(probe, "_pixel_record", pixel_record)
    monkeypatch.setattr(probe, "_decompose", decomposition)
    return SimpleNamespace(
        args=SimpleNamespace(
            root=tmp_path,
            study_plan=plan_path,
            output_dir=tmp_path / "output/research/synthetic-mask-replay",
        ),
        calls=calls,
        source_path=tmp_path / source_pins[0]["path"],
    )


@pytest.mark.parametrize("failure_kind", ["mismatch", "pixel_error"])
def test_one_failed_mask_blocks_every_decomposition_and_retains_all_12_requests(
    fake_run, monkeypatch, failure_kind
):
    def pixel_record(inputs, item):
        fake_run.calls["pixels"] += 1
        if fake_run.calls["pixels"] == 12:
            if failure_kind == "pixel_error":
                raise ValueError("synthetic original mask read failure")
            return {"reason": np.zeros((1, 1), np.uint8), "pixel_counts": {}}, {"exact": False}
        return {"reason": np.zeros((1, 1), np.uint8), "pixel_counts": {}}, {"exact": True}

    def forbidden_decomposition(*args):
        pytest.fail("No target may receive UV attribution when any mask fails equivalence.")

    monkeypatch.setattr(probe, "_pixel_record", pixel_record)
    monkeypatch.setattr(probe, "_decompose", forbidden_decomposition)
    report = probe.run(fake_run.args)
    assert fake_run.calls["pixels"] == 12
    assert len(report["records"]) == report["summary"]["requested_targets"] == 12
    assert report["summary"]["all_masks_pixel_equal"] is False
    assert report["summary"]["all_requested_verified"] is False
    assert report["summary"]["decomposition_targets"] == 0
    assert all(row["decomposition"] is None for row in report["records"])
    assert all(row["source_age"]["value"] is None for row in report["records"])
    assert report["historical_process_identity_proven"] is False
    assert report["g3_complete"] is False


def test_post_computation_pin_drift_invalidates_and_clears_all_12_decompositions(
    fake_run, monkeypatch
):
    def decomposition(inputs, item, old, reason):
        fake_run.calls["decompositions"] += 1
        if fake_run.calls["decompositions"] == 12:
            fake_run.source_path.write_text("synthetic source changed", encoding="utf-8")
        return {"synthetic_decomposition": True}

    monkeypatch.setattr(probe, "_decompose", decomposition)
    report = probe.run(fake_run.args)
    assert fake_run.calls["decompositions"] == 12
    assert report["summary"]["statuses"] == {"invalidated_input_drift": 12}
    assert report["summary"]["decomposition_targets"] == 0
    assert not report["integrity"]["all_inputs_unchanged"]
    assert all(not row.get("decomposition") for row in report["records"])
    assert not report["historical_process_identity_proven"]


def test_runner_refuses_overwriting_a_prior_output_before_any_pixel_read(fake_run):
    fake_run.args.output_dir.mkdir(parents=True)
    previous = fake_run.args.output_dir / "report.json"
    previous.write_text("prior evidence", encoding="utf-8")
    with pytest.raises(ValueError):
        probe.run(fake_run.args)
    assert fake_run.calls["pixels"] == 0
    assert previous.read_text(encoding="utf-8") == "prior evidence"
