"""Safe-loading rules from dataset plan v3 §5 that are not archive extraction.

Archive rules (zip-slip, ``tarfile`` ``filter="data"``, bombs) live in
``preprocessing/archive_preparation.py``. This module adds:

* ``torch_load_weights_only``: the only sanctioned ``torch.load`` path. The file is pinned
  by size and SHA-256 before any unpickling, read once into memory (no swap between check
  and load) and always loaded with ``weights_only=True``. A refusal is final and is never
  retried with ``weights_only=False``. ``torch`` is imported lazily and stays optional.
* ``audit_source``: a heuristic AST check (import aliases resolved per module) for
  ``torch.load`` without literal ``weights_only=True``, ``torch.jit/hub.load``, pickle-family
  loads, ``np.load(allow_pickle=...)`` other than literal ``False``, ``trust_remote_code``
  other than literal ``False``, ``**kwargs`` into those calls, ``getattr`` on sensitive
  modules, ``extract``/``extractall``/``shutil.unpack_archive`` without ``filter="data"``,
  and unsafe flags inside dict or str/bytes literals. It is not a proof of safety.

No network, model inference, ``eval`` or ``trust_remote_code`` is used here.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import io
import re
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


# Modules whose loaders deserialize code or arbitrary objects; aliases resolve to these names.
SENSITIVE_MODULES = (
    "torch",
    "numpy",
    "pickle",
    "_pickle",
    "cPickle",
    "dill",
    "joblib",
    "shutil",
    "tarfile",
)
PICKLE_MODULES = {"pickle", "_pickle", "cPickle", "dill", "joblib"}
_STRING_FLAGS = (
    (re.compile(r"weights_only\s*=\s*False"), "SENSITIVE_FLAG_IN_STRING"),
    (re.compile(r"trust_remote_code\s*=\s*True"), "SENSITIVE_FLAG_IN_STRING"),
    (re.compile(r"allow_pickle\s*=\s*True"), "SENSITIVE_FLAG_IN_STRING"),
)
# getattr(<sensitive module>, name) is flagged unless name is a literal outside this set.
_LOOKUP_NAMES = {
    "load",
    "loads",
    "Unpickler",
    "unpack_archive",
    "extract",
    "extractall",
    "jit",
    "hub",
}
# Dict keys that, when unpacked with **, would switch a loader to an unsafe mode.
_DICT_FLAGS = {"trust_remote_code": False, "allow_pickle": False, "weights_only": True}


def _sensitive(name):
    return any(name == m or name.startswith(m + ".") for m in SENSITIVE_MODULES)


class _Auditor(ast.NodeVisitor):
    """Resolve import aliases per module, then classify calls by their canonical name."""

    def __init__(self, name):
        # ``np`` is the universal numpy alias; treat it so even when the import is elsewhere.
        self.name, self.aliases, self.findings = name, {"np": "numpy"}, []

    def add(self, node, code, snippet=None):
        snippet = ast.unparse(node) if snippet is None else snippet
        self.findings.append((self.name, node.lineno, code, " ".join(snippet.split())[:200]))

    def canonical(self, node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return ""
        parts.append(node.id)
        parts.reverse()
        if parts[0] in self.aliases:
            parts[:1] = self.aliases[parts[0]].split(".")
        elif "torch" in parts[1:]:  # e.g. self.torch.load / engine.torch.load
            parts = parts[parts.index("torch") :]
        return ".".join(parts)

    def visit_Import(self, node):
        for alias in node.names:
            if alias.asname:
                self.aliases[alias.asname] = alias.name
            else:
                self.aliases[alias.name.split(".")[0]] = alias.name.split(".")[0]

    def visit_ImportFrom(self, node):
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                if node.level == 0 and _sensitive(module):
                    self.add(node, "STAR_IMPORT_FROM_SENSITIVE_MODULE")
                continue
            if node.level == 0:
                self.aliases[alias.asname or alias.name] = module + "." + alias.name

    def visit_ClassDef(self, node):
        for base in node.bases:
            name = self.canonical(base)
            if name.split(".")[0] in PICKLE_MODULES and name.endswith("Unpickler"):
                self.add(node, "PICKLE_UNPICKLER", f"class {node.name}({name})")
        self.generic_visit(node)

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value in _DICT_FLAGS:
                if not _is_constant(value, _DICT_FLAGS[key.value]):
                    self.add(node, "SENSITIVE_FLAG_IN_DICT")
        self.generic_visit(node)

    def visit_keyword(self, node):
        if node.arg == "trust_remote_code" and not _is_constant(node.value, False):
            self.add(node.value, "TRUST_REMOTE_CODE")
        self.generic_visit(node)

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return  # docstrings and bare string statements are prose, not code or patches
        self.generic_visit(node)

    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        if isinstance(value, str):
            for pattern, code in _STRING_FLAGS:
                if pattern.search(value):
                    self.add(node, code)
                    break

    def visit_Call(self, node):
        name = self.canonical(node.func)
        if (
            isinstance(node.func, ast.Name)
            and self.canonical(node.func) == "getattr"
            and node.args
            and _sensitive(self.canonical(node.args[0]))
            and not (
                len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value not in _LOOKUP_NAMES
            )
        ):
            self.add(node, "DYNAMIC_SENSITIVE_LOOKUP")
        star = any(item.arg is None for item in node.keywords)
        if name == "torch.load":
            if star or not _is_constant(_keyword(node, "weights_only"), True):
                self.add(node, "TORCH_LOAD_WITHOUT_WEIGHTS_ONLY")
        elif name in {"torch.jit.load", "torch.hub.load", "torch.hub.load_state_dict_from_url"}:
            self.add(node, "TORCH_JIT_OR_HUB_LOAD")
        elif name == "numpy.load":
            value = _keyword(node, "allow_pickle")
            if star or (value is not None and not _is_constant(value, False)):
                self.add(node, "NUMPY_ALLOW_PICKLE")
        elif name.split(".")[0] in PICKLE_MODULES and name.rsplit(".", 1)[-1] in {
            "load",
            "loads",
            "Unpickler",
        }:
            self.add(node, "PICKLE_LOAD")
        elif name == "shutil.unpack_archive":
            if star or not _is_constant(_keyword(node, "filter"), "data"):
                self.add(node, "UNPACK_ARCHIVE_WITHOUT_DATA_FILTER")
        elif isinstance(node.func, ast.Attribute) and node.func.attr in {"extractall", "extract"}:
            if star or not _is_constant(_keyword(node, "filter"), "data"):
                self.add(node, "EXTRACT_WITHOUT_DATA_FILTER")
        self.generic_visit(node)


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
    """Return findings ``(name, line, code, snippet)`` for one source; empty means clean.

    A heuristic: it recognises the listed call names (after resolving ``import ... as`` and
    ``from ... import`` aliases), ``getattr`` on sensitive modules, ``**`` unpacking into
    sensitive calls, unsafe flags inside dict and string/bytes literals (docstrings are
    skipped). Dynamic imports, values passed through variables, or code generated at run
    time are not followed, so an empty result is not a proof of safety.
    """
    auditor = _Auditor(name)
    auditor.visit(ast.parse(text, filename=name))
    return sorted(auditor.findings)


def audit_tree(root, exclude=()):
    """Audit every repository ``*.py`` file outside environment/data/output folders."""
    root = Path(root)
    findings = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in SKIPPED_DIRECTORIES or part.startswith(".venv") for part in relative.parts):
            continue
        if relative.as_posix() in exclude:
            continue
        findings += audit_source(path.read_text(encoding="utf-8"), relative.as_posix())
    return findings
