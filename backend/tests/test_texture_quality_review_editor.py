"""Self-contained draft editor publication; synthetic evidence, no reviewer certification."""

import base64
import importlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
editor = importlib.import_module("tools.texture_quality_review_editor")
spec = importlib.util.spec_from_file_location(
    "_quality_editor_fixtures", Path(__file__).with_name("test_texture_quality_review.py")
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
OUTPUT = "output/research/editor-v1"


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root, plan = fixtures.frozen.__wrapped__(tmp_path)
    for name in editor.SOURCES:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT / name).read_bytes())
    runtime = root / "synthetic-node"
    runtime.write_bytes(b"not executed; compiler is stubbed in these unit tests")
    calls = []

    def compile_stub(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command, 0, b"export function mountQualityReview() {}", b""
        )

    monkeypatch.setattr(editor.subprocess, "run", compile_stub)
    return root, plan, runtime, calls


def run(frozen, output=OUTPUT):
    root, plan, runtime, _ = frozen
    return editor.build_editor(root, plan, output, runtime)


def test_self_contained_pending_page_reuses_whole_evidence_and_exact_png_bytes(frozen):
    root, plan, runtime, calls = frozen
    report = run(frozen)
    html = (root / OUTPUT / "index.html").read_text("utf-8")
    package = json.loads(
        re.search(
            r'<script id="review-package" type="application/json">(.*?)</script>', html, re.S
        )[1]
    )
    _, expected, images = editor.review.load(root, plan)
    assert package["worksheet"] == expected
    assert len(package["images"]) == 64 and len(package["originals"]) == 8
    assert package["worksheet"]["reviewer"]["kind"] is None
    for i, row in enumerate(expected["records"]):
        for variant in editor.review.VARIANTS:
            encoded = package["images"][f"{i}/{variant}"]
            assert (
                base64.b64decode(encoded.split(",", 1)[1])
                == images[variant, row["evidence"][variant]["frame_id"]]
            )
    assert len(report["verified_inputs"]) == 764
    assert report["embedded_images"] == 72 and report["criteria"] == 320
    assert report["research_only"] is True
    assert "connect-src 'none'" in html and "form-action 'none'" in html
    assert "http://" not in html and "https://" not in html
    assert all(report[k] is False for k in editor.review.FLAGS)
    assert report["model_inference_run"] is report["saved_producer_reexecuted"] is False
    assert calls[0][0][0] == str(runtime)
    assert calls[0][1]["timeout"] == 30 and calls[0][1]["cwd"] == root


@pytest.mark.parametrize("mode", ["error", "empty", "oversized", "import", "timeout"])
def test_invalid_compilation_rejected_without_publishing(frozen, monkeypatch, mode):
    root, _, _, _ = frozen

    def broken(command, **kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 30)
        body = {
            "empty": b"",
            "oversized": b"x" * (editor.MAX_CODE + 1),
            "import": b'import("https://example.test/remote.js")',
            "error": b"error",
        }[mode]
        return subprocess.CompletedProcess(
            command, 1 if mode == "error" else 0, body, b"compiler error"
        )

    monkeypatch.setattr(editor.subprocess, "run", broken)
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        run(frozen)
    assert not (root / OUTPUT).exists()


@pytest.mark.parametrize("mode", ["source", "image", "runtime"])
def test_late_input_changes_block_publication(frozen, monkeypatch, mode):
    root, _, runtime, _ = frozen

    def drift(command, **kwargs):
        if mode == "source":
            (root / editor.SOURCES[1]).write_text("changed", encoding="utf-8")
        elif mode == "runtime":
            runtime.write_bytes(b"changed executable")
        else:
            image = next((root / "output/research/input").rglob("*.png"))
            image.write_bytes(b"changed image")
        return subprocess.CompletedProcess(
            command, 0, b"export function mountQualityReview() {}", b""
        )

    monkeypatch.setattr(editor.subprocess, "run", drift)
    with pytest.raises(ValueError):
        run(frozen)
    assert not (root / OUTPUT).exists()


def test_output_is_new_and_inside_research_before_any_compilation(frozen):
    root, _, _, calls = frozen
    with pytest.raises(ValueError):
        run(frozen, "docs/editor")
    assert not calls
    run(frozen)
    body = (root / OUTPUT / "index.html").read_bytes()
    with pytest.raises(ValueError):
        run(frozen)
    assert len(calls) == 1 and (root / OUTPUT / "index.html").read_bytes() == body


def test_embedded_metadata_cannot_close_json_script(frozen, monkeypatch):
    root, plan, _, _ = frozen
    real = editor.review.load

    def modified(root, plan):
        inputs, worksheet, images = real(root, plan)
        worksheet["scope"] = '</script><img src="https://example.test/leak">&'
        return inputs, worksheet, images

    monkeypatch.setattr(editor.review, "load", modified)
    run(frozen)
    html = (root / OUTPUT / "index.html").read_text("utf-8")
    encoded = re.search(
        r'<script id="review-package" type="application/json">(.*?)</script>', html, re.S
    )[1]
    assert "</script" not in encoded and "\\u003c" in encoded
    assert json.loads(encoded)["worksheet"]["scope"].startswith("</script>")


def test_html_budget_rejection_never_publishes(frozen, monkeypatch):
    root, _, _, _ = frozen
    monkeypatch.setattr(editor, "MAX_HTML", 100)
    with pytest.raises(ValueError, match="64 MiB"):
        run(frozen)
    assert not (root / OUTPUT).exists()
