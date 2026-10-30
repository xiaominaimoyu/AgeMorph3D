from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "tools/age_shape_mesh_probe.py"
spec = importlib.util.spec_from_file_location("age_shape_mesh_probe_tests", MODULE_PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def inspect(raw):
    assert raw[:4] == b"glTF" and struct.unpack_from("<II", raw, 4) == (2, len(raw))
    length, kind = struct.unpack_from("<I4s", raw, 12)
    assert kind == b"JSON"
    document = json.loads(raw[20 : 20 + length])
    binary_length, kind = struct.unpack_from("<I4s", raw, 20 + length)
    assert kind == b"BIN\0"
    binary = raw[28 + length :]
    assert len(binary) == binary_length
    arrays = []
    for accessor in document["accessors"]:
        view = document["bufferViews"][accessor["bufferView"]]
        dtype = "<f4" if accessor["componentType"] == 5126 else "<u4"
        arrays.append(
            np.frombuffer(
                binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]], dtype=dtype
            )
        )
    return document, arrays


@pytest.fixture
def mesh():
    raw = np.array([[10.0, 20.0, 30.0], [12.0, 20.0, 30.0], [10.0, 22.0, 30.0]])
    faces = np.array([[0, 2, 1]])
    frame = {
        "source_center": [10.0, 20.0, 30.0],
        "source_to_canonical_uniform_scale": 0.5,
        "normalization_reference": "unchanged_source_mesh",
    }
    return raw, faces, frame


def test_interleaved_xyz_neutral_reconstruction_uses_shape40_without_expression():
    mean = np.arange(9, dtype=np.float32).reshape(-1, 1)
    basis = np.zeros((9, 45), dtype=np.float32)
    basis[:, 0] = 1
    basis[:, 39] = np.arange(9)
    basis[:, 40:] = 999
    shape = np.zeros(40)
    shape[0], shape[39] = 2, 3
    result = probe.neutral_vertices(mean, basis, shape)
    np.testing.assert_array_equal(result, (np.arange(9) * 4 + 2).reshape(3, 3))
    assert result.dtype == np.float64


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_neutral_nonfinite_coefficients_fail(bad):
    shape = np.zeros(40)
    shape[0] = bad
    with pytest.raises(ValueError):
        probe.neutral_vertices(np.zeros((9, 1)), np.zeros((9, 40)), shape)


@pytest.mark.parametrize(
    "mean,basis,shape",
    [
        (np.zeros(9), np.zeros((9, 40)), np.zeros(40)),
        (np.zeros((9, 1)), np.zeros((9, 39)), np.zeros(40)),
        (np.zeros((9, 1)), np.zeros((9, 40)), np.zeros(41)),
        (np.zeros((8, 1)), np.zeros((8, 40)), np.zeros(40)),
    ],
)
def test_wrong_shape_space_is_rejected(mean, basis, shape):
    with pytest.raises(ValueError):
        probe.neutral_vertices(mean, basis, shape)


def test_static_glb_keeps_unknown_age_and_shared_original_frame(mesh):
    raw, faces, frame = mesh
    before = copy.deepcopy(frame)
    encoded, positions = probe.encode_neutral(raw, faces, frame, "a" * 64, "fgnet-001a20")
    doc, arrays = inspect(encoded)
    np.testing.assert_array_equal(positions, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    np.testing.assert_array_equal(arrays[0].reshape(-1, 3), positions)
    np.testing.assert_array_equal(arrays[1].reshape(-1, 3), [[0, 0, 1]] * 3)
    np.testing.assert_array_equal(arrays[2], [0, 1, 2])
    assert doc["extras"]["asset_mode"] == "static"
    assert doc["extras"]["source_age"] == {
        "value": None,
        "method": "unknown",
        "calibration_id": None,
    }
    assert "targets" not in doc["meshes"][0]["primitives"][0]
    assert "animations" not in doc and "images" not in doc
    assert all(
        value is False
        for key, value in doc["extras"]["research_age_shape"].items()
        if key in probe.FLAGS
    )
    shifted, _ = probe.encode_neutral(raw + [1, 0, 0], faces, frame, "a" * 64, "fgnet-001a20")
    np.testing.assert_array_equal(inspect(shifted)[1][0].reshape(-1, 3), positions + [0.5, 0, 0])
    assert frame == before
    assert probe.encode_neutral(raw.copy(), faces, frame, "a" * 64, "fgnet-001a20")[0] == encoded


@pytest.mark.parametrize(
    "faces",
    [
        np.array([[0, 0, 1]]),
        np.array([[0, 1, 9]]),
        np.array([[0, 1, 2]]),
        np.array([[0.0, 2.0, 1.0]]),
    ],
)
def test_bad_face_order_degenerate_and_out_of_bounds_fail(mesh, faces):
    raw, _, frame = mesh
    with pytest.raises(ValueError):
        probe.encode_neutral(raw, faces, frame, "a" * 64, "fgnet-001a20")


def test_float32_degenerate_geometry_is_rejected(mesh):
    raw, faces, frame = mesh
    raw[1] = raw[0]
    with pytest.raises(ValueError, match="Degenerate"):
        probe.encode_neutral(raw, faces, frame, "a" * 64, "fgnet-001a20")


@pytest.mark.parametrize(
    "source,topology", [("../source", "a" * 64), ("source", "a" * 63), ("source", "A" * 64)]
)
def test_mesh_identifier_binding_rejects_unsafe_values(mesh, source, topology):
    raw, faces, frame = mesh
    with pytest.raises(ValueError):
        probe.encode_neutral(raw, faces, frame, topology, source)


def sample(name, subject, age, failed=False):
    return {
        "sample_id": name,
        "subject_id": subject,
        "age": age,
        "group": "calibration_research",
        "status": "failed" if failed else "ok",
        "shape": None if failed else [0.0] * 40,
        "scale": None if failed else 1.0,
        "error_code": "NO_FACE" if failed else None,
    }


def test_extreme_selection_retains_failed_endpoint_ties_and_single_age_identity():
    samples = [
        sample("a20-b", "a", 20),
        sample("a20-a", "a", 20, True),
        sample("a30", "a", 30),
        sample("a40-b", "a", 40),
        sample("a40-a", "a", 40),
        sample("b25", "b", 25),
    ]
    pairs, skipped = probe.extreme_pairs(samples[::-1])
    assert pairs == [("a20-a", "a40-a"), ("a40-a", "a20-a")]
    assert skipped == [{"subject_id": "b", "reason": "SINGLE_RECORDED_AGE", "sample_ids": ["b25"]}]


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b"[]"])
def test_saved_report_duplicate_nonfinite_and_nonobject_rejected(tmp_path, body):
    (tmp_path / "report.json").write_bytes(body)
    p = {"path": "report.json", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    with pytest.raises(ValueError):
        probe.saved_report(tmp_path, p)


def test_saved_report_uses_exact_bytes_and_pin(tmp_path):
    raw = b'{"x":1}'
    (tmp_path / "report.json").write_bytes(raw)
    p = {"path": "report.json", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert probe.saved_report(tmp_path, p) == {"x": 1}
    (tmp_path / "report.json").write_bytes(b'{"x":2}')
    with pytest.raises(ValueError, match="fingerprint"):
        probe.saved_report(tmp_path, p)


@pytest.mark.parametrize(
    "output", ["outside", "output/other/x", "output/research/../outside", "../escape"]
)
def test_output_stays_in_fresh_ignored_research_directory(tmp_path, output):
    with pytest.raises(ValueError):
        probe.publish(tmp_path, output, {"test.json": b"{}"}, lambda: None)


def test_publish_checks_before_and_after_without_overwriting(tmp_path):
    calls = []
    probe.publish(tmp_path, "output/research/test", {"test.json": b"{}"}, lambda: calls.append(1))
    assert calls == [1, 1]
    assert (tmp_path / "output/research/test/test.json").read_bytes() == b"{}"
    with pytest.raises(ValueError, match="exist"):
        probe.publish(tmp_path, "output/research/test", {"test.json": b"changed"}, lambda: None)


def test_publish_drift_removes_only_owned_files(tmp_path):
    target = tmp_path / "output/research/test"
    calls = []

    def recheck():
        calls.append(1)
        if len(calls) == 2:
            (target / "external.txt").write_text("preserve", encoding="utf-8")
            raise ValueError("Input drift")

    with pytest.raises(ValueError, match="drift"):
        probe.publish(tmp_path, "output/research/test", {"test.json": b"{}"}, recheck)
    assert sorted(p.name for p in target.iterdir()) == ["external.txt"]


def test_publish_rejects_nested_artifact_names(tmp_path):
    with pytest.raises(ValueError, match="Flat"):
        probe.publish(tmp_path, "output/research/test", {"../test.json": b"{}"}, lambda: None)
