"""Safe-loading rules from dataset plan v3 §5 that are not archive extraction.

Archive rules (zip-slip, ``tarfile`` ``filter="data"``, bombs) live in
``preprocessing/archive_preparation.py``. This module adds:

* ``torch_load_weights_only``: the only sanctioned ``torch.load`` path. The file is pinned
  by size and SHA-256 before any unpickling, read once into memory (no swap between check
  and load) and always loaded with ``weights_only=True``. A refusal is final and is never
  retried with ``weights_only=False``. ``torch`` is imported lazily and stays optional.
* ``audit_source``: an AST check for ``torch.load`` without ``weights_only=True``, any
  ``trust_remote_code`` other than literal ``False``, ``np.load(allow_pickle=...)`` other
  than literal ``False`` and ``extractall`` without ``filter="data"``.

No network, model inference, ``eval`` or ``trust_remote_code`` is used here.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import io
from pathlib import Path

from . import archive_preparation as preparation
from . import resource_acquisition as acquisition

MAX_CHECKPOINT_BYTES = 4 * 1024**3
CHECKPOINT_SUFFIXES = {".pt", ".pth", ".ckpt"}
MAP_LOCATIONS = {"cpu", "cuda"}
Error, require, safe = preparation.Error, preparation.require, preparation.safe
# Folders that hold environments, data or generated output rather than repository source.
SKIPPED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "output",
    "outputs",
    "data",
    "datasets",
    "logs",
    "dist",
}


def torch_load_weights_only(
    root, pin, *, map_location="cpu", maximum=MAX_CHECKPOINT_BYTES, torch_module=None
):
    """Load a pinned checkpoint with ``weights_only=True``; never fall back."""
    root = Path(root).absolute()
    require(root.is_dir() and root == root.resolve(), "INVALID_ROOT")
    require(type(maximum) is int and 0 < maximum <= MAX_CHECKPOINT_BYTES, "INVALID_LIMIT")
    preparation._pin(pin, maximum)
    require(type(map_location) is str and map_location in MAP_LOCATIONS, "INVALID_MAP_LOCATION")
    path = safe(root, pin["path"])
    require(path.suffix.lower() in CHECKPOINT_SUFFIXES, "CHECKPOINT_SUFFIX_UNSUPPORTED")
    body = acquisition._read(path, maximum)
    require(
        len(body) == pin["bytes"] and hashlib.sha256(body).hexdigest() == pin["sha256"],
        "CHECKPOINT_PIN_MISMATCH",
    )
    if torch_module is None:
        try:
            torch_module = importlib.import_module("torch")
        except ImportError as error:
            raise Error("TORCH_UNAVAILABLE") from error
    load = torch_module.load
    try:
        accepts = "weights_only" in inspect.signature(load).parameters
    except (TypeError, ValueError):
        accepts = False
    require(accepts, "TORCH_WEIGHTS_ONLY_UNSUPPORTED")
    try:
        return load(io.BytesIO(body), map_location=map_location, weights_only=True)
    except Exception as error:  # any refusal is final; never retried with weights_only=False
        raise Error("TORCH_WEIGHTS_ONLY_REJECTED") from error


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _keyword(call, name):
    for item in call.keywords:
        if item.arg == name:
            return item.value
    return None


def _is_constant(node, value):
    return (
        isinstance(node, ast.Constant) and type(node.value) is type(value) and node.value == value
    )


def audit_source(text, name="<source>"):
    """Return findings ``(name, line, code)`` for one Python source; empty means clean."""
    findings = []
    for node in ast.walk(ast.parse(text, filename=name)):
        if isinstance(node, ast.keyword) and node.arg == "trust_remote_code":
            if not _is_constant(node.value, False):
                findings.append((name, node.value.lineno, "TRUST_REMOTE_CODE"))
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        if dotted == "torch.load" or dotted.endswith(".torch.load"):
            if not _is_constant(_keyword(node, "weights_only"), True):
                findings.append((name, node.lineno, "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY"))
        elif dotted in {"np.load", "numpy.load"}:
            value = _keyword(node, "allow_pickle")
            if value is not None and not _is_constant(value, False):
                findings.append((name, node.lineno, "NUMPY_ALLOW_PICKLE"))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "extractall":
            if not _is_constant(_keyword(node, "filter"), "data"):
                findings.append((name, node.lineno, "EXTRACTALL_WITHOUT_DATA_FILTER"))
    return findings


def audit_tree(root):
    """Audit every repository ``*.py`` file outside environment/data/output folders."""
    root = Path(root)
    findings = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in SKIPPED_DIRECTORIES or part.startswith(".venv") for part in relative.parts):
            continue
        findings += audit_source(path.read_text(encoding="utf-8"), relative.as_posix())
    return findings
