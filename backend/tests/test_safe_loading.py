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
# Known pre-existing findings, matched by (file, code, normalized snippet) so that swapping
# one unsafe call for another in the same file still fails. These are NOT verified safe:
# * sam_probe.py: two path loads with weights_only=False / no flag, no SHA-256 check before
#   loading (the hash is only written to the report afterwards);
# * sam_worker.py: hashes the path, then loads the path again (TOCTOU window);
# * sam_native_ops/install.py: a bytes patch that rewrites SAM models/psp.py to
#   weights_only=False (pSp then loads the checkpoint a second time) plus its manifest text;
# * prepare_tddfa.py: a restricted pickle.Unpickler subclass with a class allowlist, run only
#   after a SHA-256 match.
# Changing any of them is the user's decision; any new or altered finding fails the test.
KNOWN_FINDINGS = sorted(
    [
        (
            "backend/src/agemorph3d/prepare_tddfa.py",
            "PICKLE_UNPICKLER",
            "class _NumpyAssetUnpickler(pickle.Unpickler)",
        ),
        (
            "tools/sam_native_ops/install.py",
            "SENSITIVE_FLAG_IN_STRING",
            'b"ckpt = torch.load(self.opts.checkpoint_path, '
            "map_location='cpu', weights_only=False)\"",
        ),
        (
            "tools/sam_native_ops/install.py",
            "SENSITIVE_FLAG_IN_STRING",
            "'torch>=2.6 defaults weights_only=True and SAM checkpoints store opts; "
            "load the local checkpoint with weights_only=False.'",
        ),
        (
            "tools/sam_probe.py",
            "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY",
            "torch.load(checkpoint_path, map_location='cpu', weights_only=False)",
        ),
        (
            "tools/sam_probe.py",
            "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY",
            "torch.load(checkpoint_path, map_location='cpu')",
        ),
        (
            "tools/sam_worker.py",
            "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY",
            "torch.load(checkpoint, map_location='cpu', weights_only=False)",
        ),
    ]
)
# This file holds the detector's own fixtures as strings; it is the only exempt path.
AUDIT_EXCLUDE = {"backend/tests/test_safe_loading.py"}


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

T = "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"
N = "NUMPY_ALLOW_PICKLE"
X = "EXTRACT_WITHOUT_DATA_FILTER"
P = "PICKLE_LOAD"
S = "SENSITIVE_FLAG_IN_STRING"
D = "SENSITIVE_FLAG_IN_DICT"
G = "DYNAMIC_SENSITIVE_LOOKUP"
J = "TORCH_JIT_OR_HUB_LOAD"
U = "UNPACK_ARCHIVE_WITHOUT_DATA_FILTER"


@pytest.mark.parametrize(
    "source,codes",
    [
        ("torch.load(p)", [T]),
        ("torch.load(p, weights_only=False)", [T]),
        ("torch.load(p, weights_only=flag)", [T]),
        ("torch.load(p, weights_only=1)", [T]),
        ("self.torch.load(p)", [T]),
        ("torch.load(p, map_location='cpu', weights_only=True)", []),
        ("json.load(p)", []),
        ("M.from_pretrained(n, trust_remote_code=True)", ["TRUST_REMOTE_CODE"]),
        ("f(trust_remote_code=allow)", ["TRUST_REMOTE_CODE"]),
        ("f(**{}, trust_remote_code=False)", []),
        ("np.load(p, allow_pickle=True)", [N]),
        ("numpy.load(p, allow_pickle=x)", [N]),
        ("np.load(p, allow_pickle=False)", []),
        ("np.load(p)", []),
        ("archive.extractall(dest)", [X]),
        ("archive.extractall(dest, filter='fully_trusted')", [X]),
        ("archive.extractall(dest, filter='data')", []),
        # Sentinel FG-4 review bypasses, one per line.
        ("from torch import load\nload(p)", [T]),
        ("from torch import load as fetch\nfetch(p, weights_only=True)", []),
        ("from torch import load as fetch\nfetch(p)", [T]),
        ("import torch as t\nt.load(p)", [T]),
        ("import torch as t\nt.load(p, weights_only=True)", []),
        ("import torch\ngetattr(torch, 'load')(p)", [G]),
        ("import torch as t\nfn = getattr(t, name)", [G]),
        ("import numpy as n\ngetattr(n, 'load')(p, allow_pickle=True)", [G]),
        ("import pickle\ngetattr(pickle, 'loads')(b)", [G]),
        ("import tarfile\ngetattr(tarfile, 'data_filter', None)", []),
        ("import numpy as n\nn.load(p, allow_pickle=True)", [N]),
        ("from numpy import load\nload(p, allow_pickle=True)", [N]),
        ("from numpy import load as L\nL(p, allow_pickle=False)", []),
        ("np.load(p, **{'allow_pickle': True})", [N, D]),
        ("np.load(p, **options)", [N]),
        ("torch.load(p, weights_only=True, **options)", [T]),
        ("M.from_pretrained(n, **{'trust_remote_code': True})", [D]),
        ("kwargs = {'weights_only': False}", [D]),
        ("kwargs = {'weights_only': True, 'allow_pickle': False}", []),
        ("import shutil\nshutil.unpack_archive(a, d)", [U]),
        ("from shutil import unpack_archive\nunpack_archive(a, d, filter='tar')", [U]),
        ("import shutil\nshutil.unpack_archive(a, d, filter='data')", []),
        ("archive.extract(member, dest)", [X]),
        ("tarfile.TarFile.extract(archive, member, dest)", [X]),
        ("archive.extract(member, dest, filter='data')", []),
        ("import pickle\npickle.load(f)", [P]),
        ("import pickle as pk\npk.loads(b)", [P]),
        ("from pickle import loads\nloads(b)", [P]),
        ("import pickle\npickle.Unpickler(f).load()", [P]),
        ("import pickle\nclass R(pickle.Unpickler):\n    pass", ["PICKLE_UNPICKLER"]),
        ("import joblib\njoblib.load(p)", [P]),
        ("import torch\ntorch.jit.load(p)", [J]),
        ("from torch import jit\njit.load(p)", [J]),
        ("import torch\ntorch.hub.load(repo, name)", [J]),
        ("from torch import *", ["STAR_IMPORT_FROM_SENSITIVE_MODULE"]),
        ('PATCH = b"torch.load(p, weights_only=False)"', [S]),
        ("PATCH = b'model(trust_remote_code=True)'", [S]),
        ("x = 'np.load(p, allow_pickle = True)'", [S]),
        ("x = 'weights_only=True'", []),
        ('"""Docstring that mentions weights_only=False is prose."""', []),
    ],
)
def test_audit_source_detects_each_rule(source, codes):
    assert sorted(code for _, _, code, _ in loading.audit_source(source)) == sorted(codes)


def test_audit_reports_file_line_and_snippet():
    source = textwrap.dedent(
        """
        import torch

        def go(p):
            return torch.load(p)
        """
    )
    assert loading.audit_source(source, "x.py") == [
        ("x.py", 5, "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY", "torch.load(p)")
    ]


def test_audit_tree_skips_environment_data_and_output_folders(tmp_path):
    for folder in (".venv", ".venv-py31116", "node_modules", "output/research", "data", "src"):
        path = tmp_path / folder / "m.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("torch.load(p)\n", encoding="utf-8")
    expected = [("src/m.py", 1, "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY", "torch.load(p)")]
    assert loading.audit_tree(tmp_path) == expected
    assert loading.audit_tree(tmp_path, exclude={"src/m.py"}) == []


def test_repository_has_no_new_unsafe_loads():
    found = sorted(
        (name, code, snippet)
        for name, _, code, snippet in loading.audit_tree(ROOT, exclude=AUDIT_EXCLUDE)
    )
    assert found == KNOWN_FINDINGS


def test_baseline_matches_snippets_not_just_counts(tmp_path):
    """Swapping a known call for a different unsafe one keeps the count but must fail."""
    (tmp_path / "m.py").write_text("torch.load(q, weights_only=False)\n", encoding="utf-8")
    found = [(n, c, s) for n, _, c, s in loading.audit_tree(tmp_path)]
    assert found == [("m.py", T, "torch.load(q, weights_only=False)")]
    assert found != [("m.py", T, "torch.load(p, weights_only=False)")]


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
