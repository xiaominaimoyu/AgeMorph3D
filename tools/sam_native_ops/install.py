"""Install the native PyTorch StyleGAN2 op shim into the pinned SAM checkout.

The upstream op files compile CUDA extensions at import time through
``torch.utils.cpp_extension.load``. This machine has no CUDA toolkit and SAM is
only used for offline research, so the two op modules are replaced with native
implementations. The installer verifies the pinned working-tree content before
writing, is idempotent, and records the original and installed hashes.

It never touches the checkpoint, ``backend/model-manifests/`` or service state.

Usage:
    python tools/sam_native_ops/install.py --sam-root data/third_party/SAM
    python tools/sam_native_ops/install.py --sam-root data/third_party/SAM --check
    python tools/sam_native_ops/install.py --sam-root data/third_party/SAM --restore
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

# SHA-256 with CRLF normalized to LF, so clones with either line ending match.
_UPSTREAM = {
    "fused_act.py": "0732596b5e89e12c4c62d2c00c66577d889deec84b8c74419d4f1a81d2eb12a9",
    "upfirdn2d.py": "595e35cbe8b0642649bad0391c655d47d280962cb07195ee8b7d5cf16770fa56",
}
_TARGETS = ("fused_act.py", "upfirdn2d.py")
_MARKER = "NATIVE_OPS.json"
_HERE = Path(__file__).resolve().parent

# torch >= 2.6 defaults torch.load to weights_only=True, but SAM checkpoints
# store the argparse options next to the tensors.
_PSP_LOAD = b"ckpt = torch.load(self.opts.checkpoint_path, map_location='cpu')"
_PSP_LOAD_PATCHED = (
    b"ckpt = torch.load(self.opts.checkpoint_path, map_location='cpu', weights_only=False)"
)


def _sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _op_dir(root: Path) -> Path:
    return root / "models" / "stylegan2" / "op"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sam-root", type=Path, default=Path("data/third_party/SAM"))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="report state without writing")
    action.add_argument("--restore", action="store_true", help="restore upstream files via git")
    args = parser.parse_args()

    root = args.sam_root.resolve()
    op_dir = _op_dir(root)
    if not (op_dir / "__init__.py").is_file():
        raise SystemExit(f"not a SAM checkout: {root}")

    if args.restore:
        try:
            _git(
                root,
                "checkout",
                "--",
                "models/psp.py",
                *(f"models/stylegan2/op/{name}" for name in _TARGETS),
            )
        except subprocess.CalledProcessError:
            raise SystemExit(
                "git checkout failed; inspect the checkout before restoring."
            ) from None
        marker = op_dir / _MARKER
        marker.unlink(missing_ok=True)
        restored = ["models/psp.py", *(f"models/stylegan2/op/{n}" for n in _TARGETS)]
        print(json.dumps({"restored": restored}))
        return 0

    files = {}
    pending = []
    for name in _TARGETS:
        target = op_dir / name
        shim = _HERE / name
        if not target.is_file() or not shim.is_file():
            raise SystemExit(f"missing {name}")
        current, shim_hash = _sha256(target), _sha256(shim)
        upstream_hash = _UPSTREAM[name]
        if current == shim_hash:
            state = "installed"
        elif current == upstream_hash:
            state = "upstream"
            pending.append((name, shim, shim_hash))
        else:
            raise SystemExit(
                f"{name} matches neither the pinned upstream nor the shim; refusing to overwrite."
            )
        files[name] = {
            "state": state,
            "upstream_sha256": upstream_hash,
            "installed_sha256": shim_hash,
        }

    psp_path = root / "models" / "psp.py"
    psp_data = psp_path.read_bytes()
    if _PSP_LOAD_PATCHED in psp_data:
        psp_state = "installed"
    elif psp_data.count(_PSP_LOAD) == 1:
        psp_state = "upstream"
    else:
        raise SystemExit(
            "models/psp.py does not match the pinned checkpoint loader; refusing to patch."
        )

    report = {
        "schema_version": 1,
        "scope": "research-only native StyleGAN2 op shim; not a service asset",
        "sam_commit": _git(root, "rev-parse", "HEAD"),
        "files": files,
        "patches": {
            "models/psp.py": {
                "state": psp_state,
                "reason": (
                    "torch>=2.6 defaults weights_only=True and SAM checkpoints store opts; "
                    "load the local checkpoint with weights_only=False."
                ),
            }
        },
        "reason": (
            "Upstream imports compile CUDA extensions; this machine has no CUDA toolkit, "
            "and the service only needs batch=1 offline research outputs."
        ),
    }
    if args.check:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not pending and psp_state == "installed" else 1

    for name, shim, shim_hash in pending:
        (op_dir / name).write_bytes(shim.read_bytes())
        files[name]["state"] = "installed"
        files[name]["installed_sha256"] = shim_hash

    if psp_state == "upstream":
        psp_path.write_bytes(psp_data.replace(_PSP_LOAD, _PSP_LOAD_PATCHED))
        report["patches"]["models/psp.py"]["state"] = "installed"

    (op_dir / _MARKER).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"sam_commit": report["sam_commit"], "files": files}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
