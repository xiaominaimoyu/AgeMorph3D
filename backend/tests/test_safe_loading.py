"""Pinned weights-only torch loading and the repository-wide unsafe-load audit.

torch is not installed in the test environment; a stub module records each call so the
tests prove ``weights_only=True`` is always passed and a refusal is never retried.
"""

import ast
import hashlib
import importlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
loading = importlib.import_module("preprocessing.safe_loading")
CHECKPOINT = "data/models/fictional-weights.pt"
# Known pre-existing findings (SAM checkpoint loads pinned by SHA-256 before unpickling).
# Changing them is a separate decision; any new finding, or a change in these counts, fails.
KNOWN_FINDINGS = {
    ("tools/sam_probe.py", "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"): 2,
    ("tools/sam_worker.py", "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"): 1,
}


class FakeTorch:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error

    def load(self, f, map_location=None, weights_only=None):
        record = {"body": f.read(), "map_location": map_location, "weights_only": weights_only}
        self.calls.append(record)
        if self.error is not None:
            raise self.error
        return self.result


def checkpoint(root, body=b"fictional tensor bytes", name=CHECKPOINT):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def test_importing_module_does_not_import_torch():
    code = "import sys; import preprocessing.safe_loading; print('torch' in sys.modules)"
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "False"


@pytest.mark.parametrize("location", ["cpu", "cuda"])
def test_load_always_passes_weights_only_true_and_pinned_bytes(tmp_path, location):
    pin = checkpoint(tmp_path)
    fake = FakeTorch(result={"state_dict": {}})
    result = loading.torch_load_weights_only(
        tmp_path, pin, map_location=location, torch_module=fake
    )
    assert result == {"state_dict": {}}
    assert fake.calls == [
        {"body": b"fictional tensor bytes", "map_location": location, "weights_only": True}
    ]


def test_refusal_is_final_and_never_retried_with_weights_only_false(tmp_path):
    pin = checkpoint(tmp_path)
    fake = FakeTorch(error=RuntimeError("Weights only load failed: unsupported global"))
    with pytest.raises(loading.Error, match="TORCH_WEIGHTS_ONLY_REJECTED"):
        loading.torch_load_weights_only(tmp_path, pin, torch_module=fake)
    assert [call["weights_only"] for call in fake.calls] == [True]


def test_torch_without_weights_only_parameter_is_refused_before_loading(tmp_path):
    pin = checkpoint(tmp_path)
    calls = []

    class OldTorch:
        @staticmethod
        def load(f, map_location=None):
            calls.append(f)

    with pytest.raises(loading.Error, match="TORCH_WEIGHTS_ONLY_UNSUPPORTED"):
        loading.torch_load_weights_only(tmp_path, pin, torch_module=OldTorch)
    assert calls == []


def test_missing_torch_is_reported_not_fallen_back(tmp_path, monkeypatch):
    pin = checkpoint(tmp_path)
    real = importlib.import_module

    def no_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch is not installed")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(loading.importlib, "import_module", no_torch)
    with pytest.raises(loading.Error, match="TORCH_UNAVAILABLE"):
        loading.torch_load_weights_only(tmp_path, pin)


@pytest.mark.parametrize(
    "change,code",
    [
        ("sha", "CHECKPOINT_PIN_MISMATCH"),
        ("bytes", "CHECKPOINT_PIN_MISMATCH"),
        ("suffix", "CHECKPOINT_SUFFIX_UNSUPPORTED"),
        ("escape", "INVALID_PATH"),
        ("absolute", "INVALID_PATH"),
        ("location", "INVALID_MAP_LOCATION"),
        ("oversized", "INPUT_NOT_BOUNDED_FILE"),
        ("bad_pin", "INVALID_PIN"),
    ],
)
def test_checkpoint_is_rejected_before_any_unpickling(tmp_path, change, code):
    pin = checkpoint(tmp_path)
    fake, kwargs = FakeTorch(), {}
    if change == "sha":
        (tmp_path / CHECKPOINT).write_bytes(b"fictional tensor byteZ")
    elif change == "bytes":
        pin["bytes"] += 1
    elif change == "suffix":
        pin = checkpoint(tmp_path, name="data/models/fictional.pkl")
    elif change == "escape":
        pin["path"] = "../fictional-weights.pt"
    elif change == "absolute":
        pin["path"] = "/tmp/fictional-weights.pt"
    elif change == "location":
        kwargs["map_location"] = "mps:0"
    elif change == "oversized":
        pin = checkpoint(tmp_path, b"x" * 64)
        kwargs["maximum"] = 64
        (tmp_path / CHECKPOINT).write_bytes(b"x" * 65)
    else:
        pin["sha256"] = "not-a-digest"
    with pytest.raises(loading.Error, match=code):
        loading.torch_load_weights_only(tmp_path, pin, torch_module=fake, **kwargs)
    assert fake.calls == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_symlinked_checkpoint_is_refused(tmp_path):
    real = tmp_path / "elsewhere/fictional-weights.pt"
    real.parent.mkdir()
    real.write_bytes(b"fictional tensor bytes")
    (tmp_path / "data/models").mkdir(parents=True)
    (tmp_path / CHECKPOINT).symlink_to(real)
    pin = {
        "path": CHECKPOINT,
        "bytes": 22,
        "sha256": hashlib.sha256(b"fictional tensor bytes").hexdigest(),
    }
    fake = FakeTorch()
    with pytest.raises(loading.Error, match="LINK_OR_REPARSE_PATH"):
        loading.torch_load_weights_only(tmp_path, pin, torch_module=fake)
    assert fake.calls == []


def test_loader_reads_bytes_once_so_a_swap_after_hashing_is_not_loaded(tmp_path):
    pin = checkpoint(tmp_path)

    class SwappingTorch(FakeTorch):
        def load(self, f, map_location=None, weights_only=None):
            (tmp_path / CHECKPOINT).write_bytes(b"swapped malicious body")
            return super().load(f, map_location=map_location, weights_only=weights_only)

    fake = SwappingTorch()
    loading.torch_load_weights_only(tmp_path, pin, torch_module=fake)
    assert fake.calls[0]["body"] == b"fictional tensor bytes"


# --- static audit -------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,codes",
    [
        ("torch.load(p)", ["TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"]),
        ("torch.load(p, weights_only=False)", ["TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"]),
        ("torch.load(p, weights_only=flag)", ["TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"]),
        ("torch.load(p, weights_only=1)", ["TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"]),
        ("self.torch.load(p)", ["TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"]),
        ("torch.load(p, map_location='cpu', weights_only=True)", []),
        ("json.load(p)", []),
        ("M.from_pretrained(n, trust_remote_code=True)", ["TRUST_REMOTE_CODE"]),
        ("f(trust_remote_code=allow)", ["TRUST_REMOTE_CODE"]),
        ("f(**{}, trust_remote_code=False)", []),
        ("np.load(p, allow_pickle=True)", ["NUMPY_ALLOW_PICKLE"]),
        ("numpy.load(p, allow_pickle=x)", ["NUMPY_ALLOW_PICKLE"]),
        ("np.load(p, allow_pickle=False)", []),
        ("np.load(p)", []),
        ("archive.extractall(dest)", ["EXTRACTALL_WITHOUT_DATA_FILTER"]),
        ("archive.extractall(dest, filter='fully_trusted')", ["EXTRACTALL_WITHOUT_DATA_FILTER"]),
        ("archive.extractall(dest, filter='data')", []),
    ],
)
def test_audit_source_detects_each_rule(source, codes):
    assert [code for _, _, code in loading.audit_source(source)] == codes


def test_audit_reports_file_and_line():
    source = textwrap.dedent(
        """
        import torch

        def go(p):
            return torch.load(p)
        """
    )
    assert loading.audit_source(source, "x.py") == [("x.py", 5, "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY")]


def test_audit_tree_skips_environment_data_and_output_folders(tmp_path):
    for folder in (".venv", ".venv-py31116", "node_modules", "output/research", "data", "src"):
        path = tmp_path / folder / "m.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("torch.load(p)\n", encoding="utf-8")
    assert loading.audit_tree(tmp_path) == [("src/m.py", 1, "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY")]


def test_repository_has_no_new_unsafe_loads():
    counts = {}
    for name, _, code in loading.audit_tree(ROOT):
        counts[(name, code)] = counts.get((name, code), 0) + 1
    assert counts == KNOWN_FINDINGS


def test_sanctioned_modules_pass_the_audit_themselves():
    for name in ("preprocessing/safe_loading.py", "preprocessing/archive_preparation.py"):
        assert loading.audit_source((ROOT / name).read_text(encoding="utf-8"), name) == []
    # The helper calls torch through a local ``load`` name; check that call directly.
    tree = ast.parse((ROOT / "preprocessing/safe_loading.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "load"
    ]
    assert len(calls) == 1
    (weights_only,) = [k.value for k in calls[0].keywords if k.arg == "weights_only"]
    assert isinstance(weights_only, ast.Constant) and weights_only.value is True
