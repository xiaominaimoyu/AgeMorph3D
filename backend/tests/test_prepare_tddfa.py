"""Synthetic legacy NumPy fixtures only; no real-model or license acceptance claims."""

import hashlib
import json
import pickle

import pytest

np = pytest.importorskip("numpy")

from agemorph3d.prepare_tddfa import (  # noqa: E402
    CONVERSION_VERSION,
    load_verified_numpy_pickle,
    main,
    prepare_tddfa,
)


def bfm_fixture():
    vertices = 70
    return {
        "u": np.arange(vertices * 3, dtype=np.float32)[:, None],
        "w_shp": np.ones((vertices * 3, 42), dtype=np.float32),
        "w_exp": np.full((vertices * 3, 12), 2, dtype=np.float32),
        "keypoints": (np.arange(68)[:, None] * 3 + np.arange(3)).astype(np.int32).ravel(),
        # The separate tri.pkl, not this embedded topology, must be used.
        "tri": np.array([[4], [5], [6]], dtype=np.int32),
    }


def tri_fixture():
    return np.array([[0, 2], [1, 3], [2, 0]], dtype=np.int32)


def stats_fixture():
    return {
        "mean": np.arange(62, dtype=np.float32)[:, None],
        "std": np.ones((1, 62), dtype=np.float32),
    }


def dump_source(path, value, protocol=4):
    data = pickle.dumps(value, protocol=protocol)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def source_args(tmp_path):
    result = {"output_dir": tmp_path / "converted"}
    for role, value in (("bfm", bfm_fixture()), ("tri", tri_fixture()), ("stats", stats_fixture())):
        path = tmp_path / f"{role}.pkl"
        result[role] = path
        result[f"{role}_sha256"] = dump_source(path, value)
    return result


def test_conversion_preserves_raw_values_and_records_all_source_hashes(source_args) -> None:
    report = prepare_tddfa(**source_args)
    root = source_args["output_dir"]
    assert report["conversion_version"] == CONVERSION_VERSION
    assert report["coordinate_system"] == "bfm_model_raw"
    assert report["vertex_count"] == 70 and report["triangle_count"] == 2
    for role in ("bfm", "tri", "stats"):
        assert report["sources"][role]["sha256"] == source_args[f"{role}_sha256"]
    with np.load(root / "bfm.npz", allow_pickle=False) as bfm:
        np.testing.assert_array_equal(bfm["u"], bfm_fixture()["u"])
        assert bfm["w_shp"].shape == (210, 40) and bfm["w_exp"].shape == (210, 10)
        np.testing.assert_array_equal(bfm["keypoints"], bfm_fixture()["keypoints"])
        assert bfm["keypoints"].shape == (204,)
        np.testing.assert_array_equal(bfm["tri"], [[0, 1, 2], [2, 3, 0]])
        assert bfm["tri"].dtype == bfm["keypoints"].dtype == np.int64
        assert bfm["conversion_version"].item() == CONVERSION_VERSION
        assert bfm["source_bfm_sha256"].item() == source_args["bfm_sha256"]
        assert bfm["source_tri_sha256"].item() == source_args["tri_sha256"]
    with np.load(root / "param_stats.npz", allow_pickle=False) as stats:
        np.testing.assert_array_equal(stats["mean"], np.arange(62))
        assert stats["std"].shape == (62,)
        assert stats["source_stats_sha256"].item() == source_args["stats_sha256"]
    assert json.loads((root / "conversion.json").read_text(encoding="utf-8")) == report
    assert report["keypoints_semantics"] == "native_sparse_points_not_vertex_mapping"
    assert report["noncontiguous_groups"] == []
    for name in ("bfm.npz", "param_stats.npz"):
        assert (
            hashlib.sha256((root / name).read_bytes()).hexdigest()
            == report["outputs"][name]["sha256"]
        )
    assert sorted(path.name for path in root.iterdir()) == [
        "bfm.npz",
        "conversion.json",
        "param_stats.npz",
    ]


@pytest.mark.parametrize("protocol", [2, 3, 4])
def test_allowlist_handles_legacy_numpy_reconstruction_and_scalars(tmp_path, protocol) -> None:
    path = tmp_path / "legacy.pkl"
    expected = {"array": np.arange(9, dtype=np.float32).reshape(3, 3), "scalar": np.float32(1.25)}
    sha = dump_source(path, expected, protocol=protocol)
    result = load_verified_numpy_pickle(path, sha)
    np.testing.assert_array_equal(result["array"], expected["array"])
    assert result["scalar"] == expected["scalar"]


class ForbiddenCallable:
    def __reduce__(self):
        return print, ("This callable must never run during conversion.",)


def test_arbitrary_pickle_callable_is_rejected_without_execution(tmp_path, capsys) -> None:
    path = tmp_path / "forbidden.pkl"
    sha = dump_source(path, ForbiddenCallable())
    with pytest.raises(pickle.UnpicklingError, match="allowlist"):
        load_verified_numpy_pickle(path, sha)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("role", ["bfm", "tri", "stats"])
def test_all_hashes_are_checked_before_any_pickle_is_loaded(
    source_args, monkeypatch: pytest.MonkeyPatch, role
) -> None:
    source_args[f"{role}_sha256"] = "0" * 64

    def unexpected_load(*args, **kwargs):
        raise AssertionError("A hash mismatch must prevent every unpickling call.")

    monkeypatch.setattr("agemorph3d.prepare_tddfa._load_numpy_asset", unexpected_load)
    with pytest.raises(ValueError, match="SHA-256"):
        prepare_tddfa(**source_args)
    assert not source_args["output_dir"].exists()


@pytest.mark.parametrize("sha", ["", "0" * 63, "z" * 64])
def test_source_hash_is_mandatory_and_must_be_hex(tmp_path, sha) -> None:
    path = tmp_path / "data.pkl"
    path.write_bytes(b"not loaded")
    with pytest.raises(ValueError, match="SHA-256"):
        load_verified_numpy_pickle(path, sha)


def test_object_arrays_are_rejected_even_with_a_matching_hash(tmp_path) -> None:
    path = tmp_path / "object.pkl"
    sha = dump_source(path, np.array(["not numeric"], dtype=object))
    with pytest.raises(ValueError, match="Object"):
        load_verified_numpy_pickle(path, sha)


def test_multiple_pickle_objects_are_not_accepted_as_a_single_asset(tmp_path) -> None:
    path = tmp_path / "trailing.pkl"
    data = pickle.dumps(np.ones(1), protocol=4) + pickle.dumps(np.ones(2), protocol=4)
    path.write_bytes(data)
    with pytest.raises(pickle.UnpicklingError, match="Trailing"):
        load_verified_numpy_pickle(path, hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize("change", ["vertex_indices", "out_of_range", "float", "negative"])
def test_keypoints_require_204_valid_xyz_coordinate_indices(source_args, change) -> None:
    bfm = bfm_fixture()
    keypoints = bfm["keypoints"].copy()
    if change == "vertex_indices":
        keypoints = np.arange(68, dtype=np.int32)
    elif change == "out_of_range":
        keypoints[-3:] = [210, 211, 212]
    elif change == "float":
        keypoints = keypoints.astype(np.float32)
    else:
        keypoints[0] = -1
    bfm["keypoints"] = keypoints
    source_args["bfm_sha256"] = dump_source(source_args["bfm"], bfm)
    with pytest.raises(ValueError, match="keypoint"):
        prepare_tddfa(**source_args)
    assert not source_args["output_dir"].exists()


def test_native_sparse_coordinates_are_preserved_with_every_noncontiguous_group_recorded(
    source_args,
) -> None:
    bfm = bfm_fixture()
    # Reproduce the type of upstream discrepancy: z comes from another vertex.
    # Conversion must retain the source coordinate and never invent the missing z.
    bfm["keypoints"][44 * 3 + 2] = 43 * 3 + 2
    original = bfm["keypoints"].copy()
    source_args["bfm_sha256"] = dump_source(source_args["bfm"], bfm)
    report = prepare_tddfa(**source_args)
    assert report["noncontiguous_groups"] == [{"index": 44, "coordinate_indices": [132, 133, 131]}]
    assert report["keypoints_semantics"] == "native_sparse_points_not_vertex_mapping"
    with np.load(source_args["output_dir"] / "bfm.npz", allow_pickle=False) as converted:
        np.testing.assert_array_equal(converted["keypoints"], original)
        assert converted["keypoints"][44 * 3 + 2] == 131


@pytest.mark.parametrize(
    "change", ["one_based", "transposed", "float", "negative", "range", "degenerate"]
)
def test_triangle_source_is_explicit_3_by_m_zero_based_without_guessing(
    source_args, change
) -> None:
    triangles = tri_fixture()
    if change == "one_based":
        triangles += 1
    elif change == "transposed":
        triangles = triangles.T
    elif change == "float":
        triangles = triangles.astype(np.float32)
    elif change == "negative":
        triangles[0, 0] = -1
    elif change == "range":
        triangles[1, 0] = 70
    else:
        triangles[1, 0] = triangles[0, 0]
    source_args["tri_sha256"] = dump_source(source_args["tri"], triangles)
    with pytest.raises(ValueError):
        prepare_tddfa(**source_args)
    assert not source_args["output_dir"].exists()


@pytest.mark.parametrize("field", ["u", "w_shp", "w_exp"])
def test_nonfinite_or_incompatible_bfm_arrays_never_publish_outputs(source_args, field) -> None:
    bfm = bfm_fixture()
    bfm[field].flat[0] = np.nan
    source_args["bfm_sha256"] = dump_source(source_args["bfm"], bfm)
    with pytest.raises(ValueError, match="finite"):
        prepare_tddfa(**source_args)


@pytest.mark.parametrize("change", ["zero_std", "nan_mean", "wrong_shape"])
def test_parameter_stats_are_finite_62d_with_positive_std(source_args, change) -> None:
    stats = stats_fixture()
    if change == "zero_std":
        stats["std"].flat[0] = 0
    elif change == "nan_mean":
        stats["mean"].flat[0] = np.nan
    else:
        stats["mean"] = stats["mean"].reshape(2, 31)
    source_args["stats_sha256"] = dump_source(source_args["stats"], stats)
    with pytest.raises(ValueError):
        prepare_tddfa(**source_args)


def test_existing_output_is_preserved_without_overwrite(source_args) -> None:
    root = source_args["output_dir"]
    root.mkdir()
    (root / "bfm.npz").write_bytes(b"existing user output")
    with pytest.raises(FileExistsError, match="refusing"):
        prepare_tddfa(**source_args)
    assert (root / "bfm.npz").read_bytes() == b"existing user output"
    assert sorted(path.name for path in root.iterdir()) == ["bfm.npz"]


def test_cli_requires_all_hashes_and_emits_conversion_report(source_args, capsys) -> None:
    argv = []
    for key, value in source_args.items():
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    assert main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["conversion_version"] == CONVERSION_VERSION
