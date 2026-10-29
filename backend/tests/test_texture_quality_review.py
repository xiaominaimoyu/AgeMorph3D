"""Synthetic whole-cohort integrity, reviewer attribution and offline publication."""

import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "texture_quality_review", ROOT / "tools/texture_quality_review.py"
)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def put(root, name, value):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else review._encode(value)
    p.write_bytes(data)
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def frozen(tmp_path):
    policy = json.loads((ROOT / "docs/texture-quality-review-v1.json").read_text(encoding="utf-8"))
    roles = {"protocol": put(tmp_path, "docs/texture-quality-review-v1.json", policy)}
    sources = [put(tmp_path, n, (ROOT / n).read_bytes()) for n in review.SOURCES]
    stream = io.BytesIO()
    Image.new("RGBA", (1024, 1024), (10, 20, 30, 255)).save(stream, format="PNG")
    png = stream.getvalue()
    assets = []
    for i in range(10):
        source = "fgnet-004a63" if i == 0 else f"synthetic-{i:02}"
        label = 63 if i < 8 else None
        ages = (20, 45, 63, 70) if i < 7 else ((20, 63, 70) if i == 7 else (20, 45, 70))
        assets.append(
            dict(
                asset_id=source + "--original",
                source_id=source,
                sample_id=None,
                role="original_static_3d",
                source_age_label=label,
                target_age=None,
                category="baseline",
            )
        )
        for age in ages:
            sample = source + f"--sam-{age:03}"
            category = (
                "unknown_source_age"
                if label is None
                else ("same_age_control" if age == label else "other_condition")
            )
            assets.append(
                dict(
                    asset_id=sample,
                    source_id=source,
                    sample_id=sample,
                    role="sam_texture_static_3d",
                    source_age_label=label,
                    target_age=age,
                    category=category,
                )
            )
    target_ids = [a["sample_id"] for a in assets if a["sample_id"] is not None]
    roles["target_review"] = put(
        tmp_path,
        "output/research/input/mask-review.json",
        {
            "target_records": [{"sample_id": n} for n in target_ids],
            "research_only": True,
            **review.FLAGS,
        },
    )
    for variant in review.VARIANTS:
        frames, pairs = [], []
        for a in assets:
            for config in review.CONFIGS:
                material, view, background = config.split("/")
                fid = a["asset_id"] + "::" + config
                pin = put(
                    tmp_path,
                    f"output/research/input/{variant}/"
                    f"{a['asset_id']}--{config.replace('/', '--')}.png",
                    png,
                )
                frames.append(
                    dict(
                        a,
                        frame_id=fid,
                        config_id=config,
                        configuration={
                            "material_mode": material,
                            "view": view,
                            "background": background,
                        },
                        observed={
                            "geometry": {"positions": "synthetic"},
                            "invariants": {"camera": [1, 2], "transforms": [3]},
                        },
                        status="ok",
                        image=pin,
                    )
                )
                if a["sample_id"] is not None:
                    pairs.append(
                        {
                            "source_id": a["source_id"],
                            "sample_id": a["sample_id"],
                            "config_id": config,
                            "source_frame_id": a["source_id"] + "--original::" + config,
                            "target_frame_id": fid,
                        }
                    )
        capture = {
            "protocol_id": "agemorph3d-render-domain-v1",
            "status": "passed",
            "research_only": True,
            **review.FLAGS,
            "requested_frames": 376,
            "requested_pairs": 296,
            "requested_configuration": {"width": 1024, "height": 1024},
            "assets": assets,
            "frames": frames,
            "pairs": pairs,
        }
        roles[variant + "_capture"] = put(
            tmp_path, f"output/research/input/{variant}-capture.json", capture
        )
        rows = []
        for frame in frames:
            row = {k: copy.deepcopy(frame[k]) for k in (*review.FIELDS, "image")}
            row["status"] = "NO_FACE" if frame["sample_id"] in review.FOCUS else "ok"
            rows.append(row)
        identity = {
            "research_only": True,
            **review.FLAGS,
            "integrity_status": "passed",
            "frames": rows,
            "inputs": [roles[variant + "_capture"]],
        }
        roles[variant + "_identity"] = put(
            tmp_path, f"output/research/input/{variant}-identity.json", identity
        )
    plan_name = "output/research/input/plan.json"
    put(
        tmp_path,
        plan_name,
        {"schema_version": 1, "protocol_id": review.PROTOCOL, "roles": roles, "sources": sources},
    )
    return tmp_path, plan_name


def mutate_role(frozen, role, mutate):
    root, plan_name = frozen
    plan = json.loads((root / plan_name).read_bytes())
    value = json.loads((root / plan["roles"][role]["path"]).read_bytes())
    mutate(value)
    plan["roles"][role] = put(root, plan["roles"][role]["path"], value)
    # Preserve the evaluator's declared capture binding for semantic negative tests.
    if role.endswith("_capture"):
        identity_role = role.replace("_capture", "_identity")
        identity = json.loads((root / plan["roles"][identity_role]["path"]).read_bytes())
        identity["inputs"] = [plan["roles"][role]]
        plan["roles"][identity_role] = put(root, plan["roles"][identity_role]["path"], identity)
    put(root, plan_name, plan)


def test_complete_cohort_prepares_pending_and_preserves_original_bytes(frozen):
    root, plan = frozen
    inputs, worksheet, images = review.load(root, plan)
    assert len(inputs.pins) == 761 and len(images) == 80
    assert len(worksheet["cohort_targets"]) == 37
    assert len(worksheet["records"]) == 32
    for variant in review.VARIANTS:
        assert worksheet["denominators"]["saved_identity_status_counts"][variant] == {
            "ok": 344,
            "NO_FACE": 32,
        }
    report = review.run(root, plan, "output/research/prepared")
    assert report["status"] == "valid_pending" and report["answered_criteria"] == 0
    assert report["saved_png_files_verified"] == 752
    assert report["model_inference_run"] is False
    assert all(report[k] is False for k in review.FLAGS)
    assert len(list((root / "output/research/prepared").glob("*.html"))) == 9
    assert len(report["verified_inputs"]) == 761
    assert {p.name for p in (root / "output/research/prepared").iterdir()} == {
        "index.html",
        "worksheet.json",
        "report.json",
        *(c.replace("/", "--") + ".html" for c in review.CONFIGS),
    }
    html = (root / "output/research/prepared/MASK--front--black.html").read_text(encoding="utf-8")
    assert html.count("<img ") == 9 and "script-src 'none'" in html and "connect-src 'none'" in html
    assert "<script" not in html and "http://" not in html and "https://" not in html
    assert worksheet["records"][0]["source_age_api"] == review.UNKNOWN_AGE
    assert worksheet["records"][0]["source_age_research_label"] == 63
    inputs.recheck()


@pytest.mark.parametrize(
    ("role", "change"),
    [
        ("observed_capture", lambda x: x["frames"].pop()),
        ("observed_capture", lambda x: x["pairs"].pop()),
        ("observed_capture", lambda x: x["frames"].__setitem__(1, x["frames"][0])),
        ("observed_capture", lambda x: x["pairs"].__setitem__(1, x["pairs"][0])),
        ("observed_capture", lambda x: x["assets"].__setitem__(1, x["assets"][0])),
        ("observed_capture", lambda x: x["frames"][0].update(config_id="MASK/side/black")),
        (
            "observed_capture",
            lambda x: x["frames"][0]["observed"]["geometry"].update(positions="changed"),
        ),
        ("observed_capture", lambda x: x["frames"][0]["observed"]["invariants"].update(camera=[4])),
        ("observed_capture", lambda x: x.update(requested_configuration={"width": 1})),
        ("observed_capture", lambda x: x.update(g3_complete=True)),
        ("observed_identity", lambda x: x["frames"].pop()),
        ("observed_identity", lambda x: x["frames"].__setitem__(1, x["frames"][0])),
        ("observed_identity", lambda x: x["frames"][0]["image"].update(sha256="0" * 64)),
        ("observed_identity", lambda x: x.update(inputs=[])),
        ("observed_identity", lambda x: x.update(integrity_status="failed")),
        ("target_review", lambda x: x["target_records"].pop()),
        ("target_review", lambda x: x["target_records"].__setitem__(1, x["target_records"][0])),
        ("protocol", lambda x: x["limits"].update(image_bytes=99999999)),
    ],
)
def test_rejects_cohort_config_geometry_evaluator_or_gate_tampering(frozen, role, change):
    mutate_role(frozen, role, change)
    with pytest.raises((ValueError, KeyError)):
        review.run(*frozen, "output/research/rejected")
    assert not (frozen[0] / "output/research/rejected").exists()


@pytest.mark.parametrize("kind", ["human", "ai"])
def test_completed_self_report_does_not_authenticate_or_accept_quality(frozen, kind):
    root, plan = frozen
    _, expected, _ = review.load(root, plan)
    worksheet = copy.deepcopy(expected)
    worksheet["reviewer"] = {
        "kind": kind,
        "name": "Synthetic reviewer",
        "recorded_at": "2026-10-29T12:00:00+08:00",
    }
    for row in worksheet["records"]:
        for checks in row["assessments"].values():
            for check in checks.values():
                check.update(
                    rating="no_obvious_issue", note="Synthetic observation, not real visual review."
                )
    path = "output/research/filled.json"
    put(root, path, worksheet)
    report = review.run(root, plan, "output/research/collected", path)
    assert report["status"] == "valid_self_reported_complete"
    assert report["answered_criteria"] == 320
    assert report["reviewer_kind_self_reported"] == kind
    assert report["authorship_authenticated"] is False
    assert all(report[k] is False for k in review.FLAGS)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(human_review_completed=True),
        lambda x: x.update(extra_acceptance=True),
        lambda x: x["records"].pop(),
        lambda x: x["records"].__setitem__(1, x["records"][0]),
        lambda x: x["records"][0].update(config_id="changed"),
        lambda x: x["records"][0]["source_age_api"].update(value=63),
        lambda x: x["records"][0]["evidence"]["observed"].update(saved_identity_status="ok"),
        lambda x: x["plan"].update(sha256="0" * 64),
        lambda x: x["records"][0]["assessments"]["observed"]["seams"].update(rating="accepted"),
        lambda x: x["records"][0]["assessments"]["observed"]["seams"].update(
            rating="issue", note=""
        ),
        lambda x: x["records"][0]["assessments"]["observed"]["seams"].update(
            note="Unattributed pending note"
        ),
        lambda x: x["records"][0]["assessments"]["observed"]["seams"].update(note="x" * 2001),
        lambda x: x["reviewer"].update(kind="human"),
        lambda x: x["reviewer"].update(kind="human", name="A", recorded_at="2026-10-29T12:00:00"),
    ],
)
def test_worksheet_only_allows_attributed_bounded_observations(frozen, change):
    _, expected, _ = review.load(*frozen)
    worksheet = copy.deepcopy(expected)
    change(worksheet)
    with pytest.raises((ValueError, KeyError)):
        review.validate(worksheet, expected)


def test_partial_review_and_no_face_not_assessable_remain_explicit(frozen):
    _, expected, _ = review.load(*frozen)
    worksheet = copy.deepcopy(expected)
    worksheet["reviewer"] = {
        "kind": "ai",
        "name": "Synthetic AI",
        "recorded_at": "2026-10-29T04:00:00Z",
    }
    worksheet["records"][0]["assessments"]["observed"]["identity_appearance"] = {
        "rating": "not_assessable",
        "note": "Synthetic missing eye coverage; automatic NO_FACE retained.",
    }
    result = review.validate(worksheet, expected)
    assert result["status"] == "valid_pending"
    assert result["ratings"] == {
        "pending": 319,
        "issue": 0,
        "no_obvious_issue": 0,
        "not_assessable": 1,
    }
    assert worksheet["records"][0]["evidence"]["observed"]["saved_identity_status"] == "NO_FACE"


@pytest.mark.parametrize(
    "path",
    [
        "../private.json",
        "output//research/x.json",
        "C:/private.json",
        "/outside.json",
        "output\\research\\x.json",
    ],
)
def test_rejects_noncanonical_or_external_paths(tmp_path, path):
    with pytest.raises(ValueError):
        review._relative(tmp_path, path)


def test_symlink_escape_and_pin_size_type_are_rejected(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_bytes(b"private")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Host cannot create a file symlink.")
    with pytest.raises(ValueError):
        review._relative(tmp_path, "link")
    with pytest.raises(ValueError):
        review.Inputs(tmp_path).read({"path": "other", "bytes": True, "sha256": "a" * 64})


@pytest.mark.parametrize("data", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_rejects_ambiguous_or_nonfinite_json(data):
    with pytest.raises(ValueError):
        review._json(data)


def test_input_drift_rejected_and_existing_outputs_preserved(frozen):
    root, plan = frozen
    inputs, worksheet, _ = review.load(root, plan)
    output = root / "output/research/existing"
    output.mkdir(parents=True)
    (output / "owned-by-other.txt").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        review.publish(inputs, "output/research/existing", {"new.json": b"new"})
    assert (output / "owned-by-other.txt").read_bytes() == b"keep"
    image = root / worksheet["records"][0]["evidence"]["observed"]["image"]["path"]
    image.write_bytes(b"corrupted")
    with pytest.raises(ValueError):
        review.publish(inputs, "output/research/drift", {"new.json": b"new"})
    assert not (root / "output/research/drift").exists()


@pytest.mark.parametrize("kind", ["source", "metadata", "image", "bad_png"])
def test_frozen_bytes_and_png_container_are_verified(frozen, kind):
    root, plan_path = frozen
    plan = json.loads((root / plan_path).read_bytes())
    if kind == "source":
        (root / plan["sources"][1]["path"]).write_bytes(b"changed")
    elif kind == "metadata":
        (root / plan["roles"]["target_review"]["path"]).write_bytes(b"changed")
    else:
        capture_path = plan["roles"]["conservative_capture"]["path"]
        capture = json.loads((root / capture_path).read_bytes())
        if kind == "image":
            (root / capture["frames"][0]["image"]["path"]).write_bytes(b"changed")
        else:

            def change_png(report):
                name = report["frames"][0]["image"]["path"]
                report["frames"][0]["image"] = put(root, name, b"not a PNG")

            mutate_role(frozen, "conservative_capture", change_png)

            # Keep evaluator provenance aligned so the invalid PNG itself is reached.
            def update_identity(report):
                report["frames"][0]["image"] = put(
                    root, capture["frames"][0]["image"]["path"], b"not a PNG"
                )

            mutate_role(frozen, "conservative_identity", update_identity)
    with pytest.raises(ValueError):
        review.run(root, plan_path, "output/research/bad-input")
    assert not (root / "output/research/bad-input").exists()


def test_drift_after_write_removes_only_own_files(frozen, monkeypatch):
    root, plan = frozen
    inputs, _, _ = review.load(root, plan)
    original = inputs.recheck
    calls = 0

    def drift():
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "output/research/late/other.txt").write_bytes(b"not owned")
            raise ValueError("Synthetic input changed after publication.")
        original()

    monkeypatch.setattr(inputs, "recheck", drift)
    with pytest.raises(ValueError):
        review.publish(inputs, "output/research/late", {"one.json": b"1", "two.json": b"2"})
    assert sorted(p.name for p in (root / "output/research/late").iterdir()) == ["other.txt"]


def test_html_escapes_untrusted_caption_and_preserves_native_png(frozen):
    import base64
    import re

    _, worksheet, images = review.load(*frozen)
    worksheet["records"][0]["sample_id"] = "</h2><script>bad</script>"
    document = review.pages(worksheet, images)["MASK--front--black.html"].decode()
    assert "<script>bad" not in document
    assert "&lt;script&gt;bad&lt;/script&gt;" in document
    png = base64.b64decode(re.search('src="data:image/png;base64,([^"]+)"', document)[1])
    assert png == next(iter(images.values()))


def test_real_cli_reports_invalid_input_without_publishing(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "tools/texture_quality_review.py"),
            "--study-plan",
            "../outside.json",
            "--output-dir",
            "output/research/unused",
        ],
        capture_output=True,
        cwd=tmp_path,
    )
    assert result.returncode == 2
    parsed = json.loads(result.stderr)
    assert parsed["status"] == "invalid_input" and parsed["g3_complete"] is False
    assert result.stdout == b""
