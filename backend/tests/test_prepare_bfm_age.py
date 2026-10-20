"""Synthetic mapping and input-boundary checks; actual BFM is never a test fixture."""

import hashlib
import io
import json
import sys
import tarfile
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from agemorph3d import prepare_bfm_age as module  # noqa: E402


@pytest.fixture
def inputs():
    rng = np.random.default_rng(402)
    model = {
        "shapePC": rng.normal(size=(24, 199)).astype(np.float32),
        "shapeEV": np.linspace(1, 2, 199, dtype=np.float32)[:, None],
        "texPC": rng.normal(size=(24, 199)).astype(np.float32),
        "texEV": np.linspace(2, 4, 199, dtype=np.float32)[:, None],
    }
    attrs = {name: np.linspace(-0.01, 0.02, 200)[:, None] for name in ("age_shape", "age_tex")}
    indices = np.array([6, 2, 7, 0, 4])
    target = {
        "u": np.zeros((15, 1), dtype=np.float32),
        "w_shp": model["shapePC"].reshape(8, 3, 199)[indices, :, :40].reshape(15, 40),
        "tri": np.array([[0, 1, 2], [2, 3, 4]]),
        "keypoints": np.resize(np.arange(15), 204),
    }
    return model, attrs, target, indices


def test_exact_shuffled_vertex_mapping_uses_all199_with_original_stddevs(inputs):
    model, attrs, target, indices = inputs
    arrays, report = module.derive_age_arrays(model, attrs, target)
    np.testing.assert_array_equal(arrays["source_vertex_indices"], indices)
    for prefix, pc, ev, attr in (
        ("shape", "shapePC", "shapeEV", "age_shape"),
        ("texture", "texPC", "texEV", "age_tex"),
    ):
        expected = model[pc].astype(np.float64) @ (model[ev].ravel() * attrs[attr][:199].ravel())
        np.testing.assert_array_equal(
            arrays[f"{prefix}_direction"], expected.reshape(-1, 3)[indices].astype(np.float32)
        )
    assert report["pca_correspondence"] == {
        "components": 40,
        "unique_vertices": 5,
        "max_abs_error": 0,
    }
    assert report["attribute_components_used"] == 199


def test_entry200_ignored_exactly_as_original_example(inputs):
    model, attrs, target, _ = inputs
    before, _ = module.derive_age_arrays(model, attrs, target)
    attrs["age_shape"][199] = 1e100
    attrs["age_tex"][199] = -1e100
    after, _ = module.derive_age_arrays(model, attrs, target)
    np.testing.assert_array_equal(before["shape_direction"], after["shape_direction"])
    np.testing.assert_array_equal(before["texture_direction"], after["texture_direction"])


def test_one_bit_basis_difference_is_not_fitted_or_tolerated(inputs):
    model, attrs, target, _ = inputs
    target["w_shp"][0, 39] = np.nextafter(target["w_shp"][0, 39], np.float32(np.inf))
    with pytest.raises(ValueError, match="correspondence"):
        module.derive_age_arrays(model, attrs, target)


def test_duplicate_original_signature_is_ambiguous(inputs):
    model, attrs, target, _ = inputs
    model["shapePC"][3:6, :40] = model["shapePC"][:3, :40]
    with pytest.raises(ValueError, match="ambiguous"):
        module.derive_age_arrays(model, attrs, target)


def test_duplicate_cropped_vertices_are_rejected(inputs):
    model, attrs, target, _ = inputs
    target["w_shp"][3:6] = target["w_shp"][:3]
    with pytest.raises(ValueError, match="one-to-one"):
        module.derive_age_arrays(model, attrs, target)


@pytest.mark.parametrize(
    "section,name,value",
    [
        ("model", "shapeEV", np.zeros((199, 1))),
        ("model", "texPC", np.ones((24, 198))),
        ("attrs", "age_shape", np.ones((199, 1))),
        ("attrs", "age_tex", np.full((200, 1), np.nan)),
        ("target", "w_shp", np.ones((15, 40), dtype=np.float64)),
        ("target", "tri", np.array([[0, 1, 100]])),
        ("target", "tri", np.array([[0, 0, 1]])),
        ("target", "keypoints", np.zeros(204, dtype=np.float32)),
        ("target", "u", np.full((15, 1), np.inf)),
    ],
)
def test_invalid_numeric_models_are_rejected(inputs, section, name, value):
    model, attrs, target, _ = inputs
    {"model": model, "attrs": attrs, "target": target}[section][name] = value
    with pytest.raises(ValueError):
        module.derive_age_arrays(model, attrs, target)


@pytest.fixture
def prepared_args(tmp_path, inputs, monkeypatch):
    model, attrs, target, _ = inputs
    source = tmp_path / "original.tgz"
    source.write_bytes(b"synthetic archive validated by isolated reader fixture")
    cropped = tmp_path / "cropped.npz"
    np.savez(cropped, **target)
    monkeypatch.setattr(
        module, "_load_original", lambda data: (model, attrs, {"fixture": "f" * 64})
    )
    return {
        "bfm_archive": source,
        "bfm_archive_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "target_bfm": cropped,
        "target_bfm_sha256": hashlib.sha256(cropped.read_bytes()).hexdigest(),
        "output_dir": tmp_path / "prepared",
    }


def test_conversion_writes_only_bound_native_strength_outputs(prepared_args):
    report = module.prepare_bfm_age(**prepared_args)
    output = prepared_args["output_dir"]
    assert sorted(path.name for path in output.iterdir()) == [
        "age_direction.npz",
        "provenance.json",
    ]
    assert report == json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert report["years_calibrated"] is False and report["g3_accepted"] is False
    assert report["unit"] == "bfm_attribute_strength"
    assert report["source_sha256"] == prepared_args["bfm_archive_sha256"]
    assert report["target_bfm_sha256"] == prepared_args["target_bfm_sha256"]
    assert (
        report["output"]["sha256"]
        == hashlib.sha256((output / "age_direction.npz").read_bytes()).hexdigest()
    )
    with np.load(output / "age_direction.npz", allow_pickle=False) as data:
        assert data["years_calibrated"].item() is False
        assert data["topology_sha256"].item() == report["topology_sha256"]


@pytest.mark.parametrize("key", ["bfm_archive_sha256", "target_bfm_sha256"])
def test_all_hashes_checked_before_any_archive_parsing(prepared_args, monkeypatch, key):
    prepared_args[key] = "0" * 64

    def unexpected(data):
        pytest.fail("Archive parsing must not precede both input hashes.")

    monkeypatch.setattr(module, "_load_original", unexpected)
    with pytest.raises(ValueError, match="SHA-256"):
        module.prepare_bfm_age(**prepared_args)
    assert not prepared_args["output_dir"].exists()


def test_no_overwrite_and_failed_second_write_removes_only_own_outputs(prepared_args, monkeypatch):
    output = prepared_args["output_dir"]
    output.mkdir()
    keep = output / "unrelated.txt"
    keep.write_text("preserve")
    original_open = type(output).open

    def fail_report(path, *args, **kwargs):
        if path.name == "provenance.json":
            raise OSError("simulated second write failure")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(type(output), "open", fail_report)
        with pytest.raises(OSError):
            module.prepare_bfm_age(**prepared_args)
    assert sorted(path.name for path in output.iterdir()) == ["unrelated.txt"]
    assert keep.read_text() == "preserve"
    module.prepare_bfm_age(**prepared_args)
    with pytest.raises(ValueError, match="overwrite"):
        module.prepare_bfm_age(**prepared_args)


def tar_fixture(*, duplicate=False, linked=False, oversized=False):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        names = (
            module._MODEL_MEMBER,
            module._ATTR_MEMBER,
            module._EXAMPLE_MEMBER,
            module._RECON_MEMBER,
        )
        for name in (*names, *([names[0]] if duplicate else [])):
            member = tarfile.TarInfo(name)
            member.size = 1
            if linked and name == names[0]:
                member.type = tarfile.SYMTYPE
                member.linkname = "elsewhere"
                member.size = 0
            archive.addfile(member, io.BytesIO(b"x"))
        if oversized:
            member = tarfile.TarInfo("huge-unselected")
            member.size = module._MAX_TAR_BYTES + 1
            # Metadata alone is enough: the reader must reject before trying data.
            archive.fileobj.write(member.tobuf())
    return buffer.getvalue()


@pytest.mark.parametrize("case", ["duplicate", "linked", "oversized"])
def test_selected_archive_members_cannot_be_ambiguous_linked_or_oversized(monkeypatch, case):
    monkeypatch.setitem(sys.modules, "scipy", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "scipy.io",
        SimpleNamespace(loadmat=lambda *args, **kwargs: {}, whosmat=lambda *args: []),
    )
    with pytest.raises(ValueError):
        module._load_original(tar_fixture(**{case: True}))


def test_oversized_mat_dimensions_are_rejected_before_numeric_allocation(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Oversized MAT declarations must not reach loadmat.")

    declared = [
        ("shapePC", (300_000_000, 199), "single"),
        ("shapeEV", (199, 1), "single"),
        ("texPC", (24, 199), "single"),
        ("texEV", (199, 1), "single"),
    ]
    monkeypatch.setitem(sys.modules, "scipy", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "scipy.io",
        SimpleNamespace(loadmat=unexpected, whosmat=lambda *args: declared),
    )
    with pytest.raises(ValueError, match="dimensions"):
        module._load_original(tar_fixture())


def test_npz_object_values_never_enable_pickle():
    buffer = io.BytesIO()
    np.savez(
        buffer,
        u=np.array([object()], dtype=object),
        w_shp=np.ones(1),
        tri=np.ones(1),
        keypoints=np.ones(1),
    )
    with pytest.raises(ValueError, match="Object arrays"):
        module._target_arrays(buffer.getvalue())
