"""Tiny synthetic assets/sessions only: these tests do not establish real B0 success."""

from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
pytest.importorskip("onnxruntime")

from agemorph3d.tddfa import TddfaOnnx, TddfaResult, _prepare_input, project_vertices  # noqa: E402


def synthetic_bfm() -> dict[str, np.ndarray]:
    # Four vertices suffice to expose xyz ordering and independent shape/expression terms.
    shape_basis = np.zeros((12, 40), dtype=np.float32)
    shape_basis[0, 0] = 2
    expr_basis = np.zeros((12, 10), dtype=np.float32)
    expr_basis[4, 0] = 3
    return {
        "u": np.arange(12, dtype=np.float32)[:, None],
        "w_shp": shape_basis,
        "w_exp": expr_basis,
        "tri": np.array([[0, 1, 2], [2, 3, 0]], dtype=np.int32),
        "keypoints": np.arange(204, dtype=np.int32) % 12,
    }


def synthetic_stats() -> dict[str, np.ndarray]:
    return {"mean": np.zeros(62, dtype=np.float32), "std": np.ones(62, dtype=np.float32)}


def test_projection_returns_original_pixels_without_changing_raw_vertices():
    vertices = np.array([[1, 20, 3], [61, 80, 8]], dtype=np.float32)
    result = TddfaResult(
        shape=np.zeros(40),
        expr=np.zeros(10),
        vertices=vertices,
        triangles=np.array([[0, 1, 0]]),
        projection=np.eye(3, 4, dtype=np.float32),
        roi=(10, 20, 250, 140),
        topology_sha256="synthetic",
    )
    np.testing.assert_allclose(project_vertices(result), [[10, 120, 0], [130, 60, 7.5]])
    np.testing.assert_array_equal(result.vertices, [[1, 20, 3], [61, 80, 8]])


@pytest.fixture
def assets(tmp_path: Path):
    bfm_path, stats_path = tmp_path / "bfm.npz", tmp_path / "param_stats.npz"
    regressor_path = tmp_path / "regressor.onnx"
    regressor_path.write_bytes(b"synthetic session substitute; never a real ONNX model")
    np.savez(bfm_path, **synthetic_bfm())
    np.savez(stats_path, **synthetic_stats())
    return SimpleNamespace(
        paths={"regressor": regressor_path, "bfm": bfm_path, "param_stats": stats_path},
        manifest=SimpleNamespace(backend="3ddfa_v2_onnx"),
        license_verified=False,
    )


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch):
    fake = SimpleNamespace(
        input_name="face_input",
        output_name="regressed_parameters",
        input_shape=[1, 3, 120, 120],
        output_shape=[1, 62],
        input_type="tensor(float)",
        output_type="tensor(float)",
        providers=["CPUExecutionProvider"],
        prediction=np.zeros((1, 62), dtype=np.float32),
        calls=[],
    )

    class SyntheticSession:
        def __init__(self, path, *, sess_options, providers):
            fake.path = path
            fake.options = sess_options
            fake.requested_providers = providers

        def get_providers(self):
            return fake.providers

        def get_inputs(self):
            return [
                SimpleNamespace(name=fake.input_name, type=fake.input_type, shape=fake.input_shape)
            ]

        def get_outputs(self):
            return [
                SimpleNamespace(
                    name=fake.output_name, type=fake.output_type, shape=fake.output_shape
                )
            ]

        def run(self, outputs, inputs):
            fake.calls.append((outputs, inputs))
            return [fake.prediction]

    monkeypatch.setattr("agemorph3d.tddfa.ort.InferenceSession", SyntheticSession)
    return fake


def test_rgb_to_bgr_normalization_and_zero_padding_have_fixed_numeric_values() -> None:
    rgb = np.empty((100, 100, 3), dtype=np.uint8)
    rgb[:] = [10, 20, 30]
    tensor, roi = _prepare_input(rgb, [0, 0, 100, 100])
    assert roi == (-29, -15, 129, 143)
    assert tensor.shape == (1, 3, 120, 120)
    assert tensor.dtype == np.float32 and tensor.flags.c_contiguous
    np.testing.assert_allclose(tensor[0, :, 60, 60], (np.array([30, 20, 10]) - 127.5) / 128)
    np.testing.assert_array_equal(tensor[0, :, 0, 0], np.full(3, -127.5 / 128))
    np.testing.assert_array_equal(rgb[0, 0], [10, 20, 30])


def test_roi_uses_xywh_center_shift_integer_expansion_and_rounded_crop() -> None:
    rgb = np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3)
    tensor, roi = _prepare_input(rgb, [1, 1, 7, 5])
    assert roi == pytest.approx([0, -0.16, 9, 8.84])
    # Those floating boundaries round to a 9 x 9 canvas; bottom/right remain black.
    canvas = np.zeros((9, 9, 3), dtype=np.uint8)
    canvas[:6, :8] = rgb[..., ::-1]
    expected = cv2.resize(canvas, (120, 120), interpolation=cv2.INTER_LINEAR)
    expected = (expected.astype(np.float32) - 127.5) / 128
    np.testing.assert_array_equal(tensor[0].transpose(1, 2, 0), expected)


@pytest.mark.parametrize(
    "bbox",
    [
        [],
        [0, 0, 2],
        [0, 0, 0, 1],
        [0, 0, -1, 2],
        [0, 0, 1, np.nan],
        [0, 0, np.inf, 2],
        [20, 0, 1, 1],
        [-4, 0, 1, 1],
        [0, 0, 0.01, 0.01],
        [0, 0, 1e6, 1e6],
    ],
)
def test_invalid_bbox_is_rejected_before_allocating_an_unbounded_crop(bbox) -> None:
    with pytest.raises(ValueError):
        _prepare_input(np.zeros((10, 10, 3), dtype=np.uint8), bbox)


@pytest.mark.parametrize(
    "image",
    [
        np.zeros((3, 3)),
        np.zeros((3, 3, 3)),
        np.zeros((3, 3, 4), dtype=np.uint8),
        np.zeros((0, 3, 3), dtype=np.uint8),
        [[[0, 0, 0]]],
    ],
)
def test_input_requires_a_nonempty_uint8_rgb_array(image) -> None:
    with pytest.raises(ValueError):
        _prepare_input(image, [0, 0, 1, 1])


def test_cpu_regression_reverses_standardization_and_retains_raw_geometry(assets, session) -> None:
    stats = synthetic_stats()
    stats["mean"][:12] = np.arange(12)
    stats["mean"][12], stats["std"][12] = 4, 2
    stats["mean"][52], stats["std"][52] = 5, 3
    np.savez(assets.paths["param_stats"], **stats)
    session.prediction[0, 12], session.prediction[0, 52] = 2, -1
    model = TddfaOnnx(assets)
    result = model.reconstruct(np.zeros((10, 10, 3), dtype=np.uint8), [0, 0, 10, 10])

    assert session.requested_providers == ["CPUExecutionProvider"]
    assert session.path == assets.paths["regressor"].read_bytes()
    assert session.options.intra_op_num_threads == session.options.inter_op_num_threads == 1
    assert session.calls[0][0] == ["regressed_parameters"]
    assert set(session.calls[0][1]) == {"face_input"}
    assert model.license_verified is False
    assert result.coordinate_system == "bfm_model_raw"
    assert result.shape.shape == (40,) and result.expr.shape == (10,)
    assert result.shape[0] == 8 and result.expr[0] == 2
    np.testing.assert_array_equal(result.projection, np.arange(12).reshape(3, 4))
    expected_vertices = np.arange(12, dtype=np.float32).reshape(4, 3)
    expected_vertices[0, 0] += 16
    expected_vertices[1, 1] += 6
    np.testing.assert_array_equal(result.vertices, expected_vertices)
    assert result.vertices.dtype == np.float32
    assert not hasattr(result, "pose")
    assert result.topology_sha256 == model.topology_sha256
    assert len(result.topology_sha256) == 64


@pytest.mark.parametrize("field", ["u", "w_shp", "w_exp", "tri", "keypoints"])
def test_missing_bfm_arrays_are_rejected(assets, session, field: str) -> None:
    bfm = synthetic_bfm()
    del bfm[field]
    np.savez(assets.paths["bfm"], **bfm)
    with pytest.raises(ValueError, match="missing"):
        TddfaOnnx(assets)


@pytest.mark.parametrize(
    "field,value",
    [
        ("u", np.zeros(12)),
        ("u", np.zeros((11, 1))),
        ("u", np.full((12, 1), np.nan)),
        ("w_shp", np.zeros((12, 39))),
        ("w_shp", np.zeros((9, 40))),
        ("w_exp", np.zeros((12, 9))),
        ("w_exp", np.full((12, 10), np.inf)),
        ("tri", np.array([[0, 1, 4]])),
        ("tri", np.array([[0, -1, 2]])),
        ("tri", np.array([[0, 0, 2]])),
        ("tri", np.array([[0.0, 1, 2]])),
        ("tri", np.array([0, 1, 2])),
        ("keypoints", np.zeros(67, dtype=np.int32)),
        ("keypoints", np.full(204, 12, dtype=np.int32)),
    ],
)
def test_bfm_shape_finite_and_topology_invariants(assets, session, field: str, value) -> None:
    bfm = synthetic_bfm()
    bfm[field] = value
    np.savez(assets.paths["bfm"], **bfm)
    with pytest.raises(ValueError):
        TddfaOnnx(assets)


def test_npz_object_arrays_never_enable_pickle_loading(assets, session) -> None:
    bfm = synthetic_bfm()
    bfm["u"] = np.array([{"not": "a numeric model"}], dtype=object)
    np.savez(assets.paths["bfm"], **bfm)
    with pytest.raises(ValueError, match="allow_pickle=False"):
        TddfaOnnx(assets)


def test_pickle_and_non_npz_assets_are_rejected(assets, session) -> None:
    assets.paths["bfm"] = assets.paths["bfm"].with_suffix(".pkl")
    with pytest.raises(ValueError, match="safe NPZ"):
        TddfaOnnx(assets)


@pytest.mark.parametrize(
    "field,value",
    [
        ("mean", np.zeros((1, 62))),
        ("mean", np.full(62, np.inf)),
        ("std", np.zeros(62)),
        ("std", -np.ones(62)),
        ("std", np.ones(61)),
    ],
)
def test_parameter_stats_require_62_finite_values_and_positive_std(
    assets, session, field: str, value
) -> None:
    stats = synthetic_stats()
    stats[field] = value
    np.savez(assets.paths["param_stats"], **stats)
    with pytest.raises(ValueError):
        TddfaOnnx(assets)


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_shape", [1, 3, 128, 128]),
        ("input_shape", ["batch", 3, 120, 120]),
        ("output_shape", [1, 72]),
        ("input_type", "tensor(double)"),
        ("output_type", "tensor(int64)"),
        ("providers", ["CUDAExecutionProvider"]),
        ("providers", ["CPUExecutionProvider", "CUDAExecutionProvider"]),
    ],
)
def test_session_contract_is_fixed_and_cpu_only(assets, session, field: str, value) -> None:
    setattr(session, field, value)
    with pytest.raises(ValueError):
        TddfaOnnx(assets)


@pytest.mark.parametrize(
    "prediction",
    [
        np.zeros(62, dtype=np.float32),
        np.zeros((1, 72), dtype=np.float32),
        np.full((1, 62), np.nan, dtype=np.float32),
        np.full((1, 62), np.inf, dtype=np.float32),
    ],
)
def test_invalid_regressor_output_cannot_produce_geometry(assets, session, prediction) -> None:
    model = TddfaOnnx(assets)
    session.prediction = prediction
    with pytest.raises(ValueError):
        model.reconstruct(np.zeros((10, 10, 3), dtype=np.uint8), [0, 0, 10, 10])


def test_finite_inputs_that_overflow_vertex_arithmetic_are_rejected(assets, session) -> None:
    bfm = synthetic_bfm()
    bfm["w_shp"][0, 0] = 1e30
    np.savez(assets.paths["bfm"], **bfm)
    session.prediction[0, 12] = 1e30
    model = TddfaOnnx(assets)
    with pytest.raises(ValueError, match="overflowed"):
        model.reconstruct(np.zeros((10, 10, 3), dtype=np.uint8), [0, 0, 10, 10])


def test_topology_hash_is_dtype_independent_and_sensitive_to_face_order(assets, session) -> None:
    first = TddfaOnnx(assets)
    bfm = synthetic_bfm()
    bfm["tri"] = bfm["tri"].astype(np.uint16)
    bfm["keypoints"] = bfm["keypoints"].astype(np.int64)
    np.savez(assets.paths["bfm"], **bfm)
    equivalent = TddfaOnnx(assets)
    assert first.topology_sha256 == equivalent.topology_sha256
    assert not first.triangles.flags.writeable and not first.keypoint_coordinates.flags.writeable
    bfm["tri"] = bfm["tri"][::-1]
    np.savez(assets.paths["bfm"], **bfm)
    reordered = TddfaOnnx(assets)
    assert reordered.topology_sha256 != first.topology_sha256


@pytest.mark.parametrize("change", ["backend", "missing_role", "extra_role"])
def test_manifest_backend_and_exact_asset_roles_are_required(assets, session, change) -> None:
    if change == "backend":
        assets.manifest.backend = "yolov5_face_onnx"
    elif change == "missing_role":
        del assets.paths["regressor"]
    else:
        assets.paths["detector"] = assets.paths["regressor"]
    with pytest.raises(ValueError, match="exactly"):
        TddfaOnnx(assets)
    assert not hasattr(session, "path")


def test_onnx_size_budget_is_checked_before_session_creation(
    assets, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agemorph3d.tddfa._MAX_ONNX_BYTES", 1)
    with pytest.raises(ValueError, match="128 MiB"):
        TddfaOnnx(assets)
    assert not hasattr(session, "path")


@pytest.mark.parametrize("limit_kind", ["member", "total"])
def test_npz_member_and_cumulative_unpacked_budgets_precede_array_loading(
    assets, session, monkeypatch: pytest.MonkeyPatch, limit_kind
) -> None:
    with ZipFile(assets.paths["bfm"]) as archive:
        sizes = [entry.file_size for entry in archive.infolist()]
    budget = 1 if limit_kind == "member" else max(sizes)
    assert budget < sum(sizes)
    monkeypatch.setattr("agemorph3d.tddfa._MAX_NPZ_BYTES", budget)

    def unexpected_array_load(*args, **kwargs):
        raise AssertionError("Unpacking must not happen before the archive budget check.")

    monkeypatch.setattr("agemorph3d.tddfa.np.load", unexpected_array_load)
    with pytest.raises(ValueError, match="unpacked budget"):
        TddfaOnnx(assets)


def test_npz_duplicate_entries_and_broken_archives_are_rejected(assets, session) -> None:
    with ZipFile(assets.paths["bfm"], mode="a") as archive:
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("u.npy", b"ambiguous duplicate")
    with pytest.raises(ValueError, match="ambiguous"):
        TddfaOnnx(assets)
    assets.paths["bfm"].write_bytes(b"not a valid npz archive")
    with pytest.raises(ValueError, match="valid ZIP"):
        TddfaOnnx(assets)
