"""K5 preparation integration, exact/view evidence, failure ledgers and frozen inputs."""

import copy
import hashlib
import importlib
import importlib.util
import io
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
data = importlib.import_module("preprocessing.duplicate_screening")
spec = importlib.util.spec_from_file_location(
    "_duplicate_preparation_fixtures", Path(__file__).with_name("test_archive_preparation.py")
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
OUTPUT = "output/research/screened-v1"


def encoded(image, **kwargs):
    stream = io.BytesIO()
    image.save(stream, format="PNG", **kwargs)
    return stream.getvalue()


def raster():
    image = Image.new("RGB", (16, 16))
    image.putdata([(x * 15, y * 15, (x * 7 + y * 9) % 256) for y in range(16) for x in range(16)])
    return image


def make_case(root, bodies=None):
    if bodies is None:
        with raster() as image, ImageOps.mirror(image) as mirror:
            raw = encoded(image)
            bodies = [raw, raw, encoded(mirror)]
    case = fixtures.make_case(
        root, members=[(f"images/{i}.png", body) for i, body in enumerate(bodies)]
    )
    for i, row in enumerate(case["manifest"]["records"]):
        row["use"] = data.metadata.RESEARCH_USES[i % 3]
    case["manifest"]["records"][0].update(
        subject_id="A",
        age=data.metadata.age_label("exact", 45),
        age_source="dataset_annotation",
        processing={"status": "failed", "reason": "historical:NO_FACE"},
    )
    if len(case["manifest"]["records"]) > 2:
        case["manifest"]["records"][2].update(
            age=data.metadata.age_label("interval", lower=30, upper=40),
            age_source="dataset_annotation",
        )
    source = fixtures.run(case)
    case["source"] = source
    case["prepared"] = json.loads(
        (root / fixtures.OUTPUT / "prepared-manifest.json").read_text(encoding="utf-8")
    )
    case["plan"] = {
        "schema_id": data.SCHEMA,
        "plan_id": "synthetic-screen-v1",
        "preparation_report": fixtures.pin(root, root / fixtures.OUTPUT / "report.json"),
        "prepared_manifest": fixtures.pin(root, root / fixtures.OUTPUT / "prepared-manifest.json"),
        "fingerprint_contract": data.fingerprint_contract(),
        "algorithm_sources": [],
        "reserve_bytes": 0,
    }
    for name in data.ALGORITHM_SOURCES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
        case["plan"]["algorithm_sources"].append(fixtures.pin(root, target))
    return case


def freeze(case):
    path = case["root"] / "output/research/input/screen-plan.json"
    fixtures.save_json(path, case["plan"])
    return path.relative_to(case["root"]).as_posix(), fixtures.sha(path.read_bytes())


def run(case, output=OUTPUT):
    name, digest = freeze(case)
    return data.screen(case["root"], name, digest, output)


def change_report(case):
    path = case["root"] / fixtures.OUTPUT / "report.json"
    value = {k: v for k, v in case["source"].items() if k != "receipt"}
    fixtures.save_json(path, value)
    case["plan"]["preparation_report"] = fixtures.pin(case["root"], path)


@pytest.fixture(autouse=True)
def clean_readonly(tmp_path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_complete_k5_preserved_exact_groups_mirrors_and_pending_review(tmp_path):
    case = make_case(tmp_path)
    before = [
        fixtures.pin(tmp_path, tmp_path / r["normalized"]["path"])
        for r in case["source"]["records"]
    ]
    report = run(case)
    assert report["status"] == "passed" and report["inputs_stable"]
    assert [r["k5"] for r in report["records"]] == case["prepared"]["records"]
    assert report["records"][0]["k5"]["processing"]["reason"] == "historical:NO_FACE"
    assert report["records"][1]["k5"]["age"] == data.metadata.age_label("unknown")
    assert report["summary"] == {
        "requested_images": 3,
        "fingerprinted_images": 3,
        "failed_images": 0,
        "images_before_final_check": 3,
        "requested_pairs": 3,
        "comparable_pairs": 3,
        "uncomparable_pairs": 0,
        "candidate_pairs": 3,
        "cross_use_candidate_pairs": 3,
    }
    assert len(report["pair_ledger"]) == 3
    exact = next(g for g in report["exact_groups"] if g["kind"] == "normalized_file_sha256")
    assert exact["image_indices"] == [0, 1] and exact["cross_assigned_uses"]
    mirror = report["candidates"][1]
    assert not mirror["same_normalized_file_sha256"]
    assert {tuple(p.values()) for p in mirror["equal_rgb_pixel_view_pairs"]} == {
        ("original", "mirror"),
        ("mirror", "original"),
    }
    assert all(c["review_status"] == "pending" for c in report["candidates"])
    assert all(c["same_declared_local_subject"] is None for c in report["candidates"])
    assert report["metadata_audit"] == data.metadata.audit_manifest(case["prepared"])
    assert all(report[k] is False for k in data.acquisition.FLAGS)
    assert all(
        report[k] is False
        for k in (
            "candidate_review_complete",
            "no_leakage_accepted",
            "cross_source_identity_proven",
            "original_binary_integrity_rechecked",
            "images_or_thumbnails_written",
            "split_assignment_performed",
            "model_inference_run",
        )
    )
    assert [fixtures.pin(tmp_path, tmp_path / p["path"]) for p in before] == before
    assert sorted(p.name for p in (tmp_path / OUTPUT).iterdir()) == ["report.json"]


def test_only_normalized_pinned_files_are_read_no_originals(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    originals = (tmp_path / fixtures.OUTPUT / "files").resolve()
    original_open = Path.open

    def guard(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(originals), "Original image read attempted"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    assert run(case)["summary"]["fingerprinted_images"] == 3


def test_alpha_is_explicitly_ignored_by_rgb_but_file_hashes_differ(tmp_path):
    bodies = []
    for alpha in (0, 255):
        with Image.new("RGBA", (16, 16), (40, 60, 80, alpha)) as image:
            bodies.append(encoded(image))
    report = run(make_case(tmp_path, bodies))
    pair = report["candidates"][0]
    assert not pair["same_normalized_file_sha256"]
    assert len(pair["equal_rgb_pixel_view_pairs"]) == len(pair["matched_view_pairs"]) == 4
    assert all(g["kind"] == "rgb_pixel_sha256" for g in report["exact_groups"])
    assert "ignores alpha" in report["rgb_pixel_semantics"]


def test_flat_different_colors_are_candidates_not_exact_duplicates(tmp_path):
    bodies = []
    for color in ("black", "white"):
        with Image.new("RGB", (16, 16), color) as image:
            bodies.append(encoded(image))
    report = run(make_case(tmp_path, bodies))
    pair = report["candidates"][0]
    assert not pair["same_normalized_file_sha256"] and pair["equal_rgb_pixel_view_pairs"] == []
    assert len(pair["matched_view_pairs"]) == 4
    assert all(p["gray32_mae"] == 1 for p in pair["matched_view_pairs"])
    assert report["exact_groups"] == []


def test_source_preparation_failures_keep_all_images_and_pairs(tmp_path):
    with raster() as image:
        raw = encoded(image)
    report = run(make_case(tmp_path, [raw, b"not an image", raw]))
    assert report["status"] == "failed" and report["inputs_stable"]
    assert report["summary"]["requested_pairs"] == 3
    assert report["summary"]["comparable_pairs"] == 1
    assert report["summary"]["uncomparable_pairs"] == 2
    bad = report["records"][1]
    assert bad["error_code"] == "SOURCE_PREPARATION_FAILED"
    assert bad["preparation_error_code"] == "IMAGE_DECODE_FAILED"
    assert bad["read_attempted"] is False and bad["normalized"] is None


@pytest.mark.parametrize(
    "relation", ["same_local", "different_local", "same_linked", "cross_dataset"]
)
def test_subject_declarations_and_unassigned_use_are_not_inferred(tmp_path, relation):
    case = make_case(tmp_path)
    path = tmp_path / fixtures.OUTPUT / "prepared-manifest.json"
    original_path = case["manifest_path"]
    original = json.loads(original_path.read_text(encoding="utf-8"))
    prepared = case["prepared"]
    for packet in (original, prepared):
        a, b = packet["records"][:2]
        b["use"] = "unassigned"
        if relation in {"same_local", "different_local", "cross_dataset"}:
            b["subject_id"] = "B" if relation == "different_local" else "A"
        if relation == "same_linked":
            a["linked_subject_id"] = b["linked_subject_id"] = "link-A"
        if relation == "cross_dataset":
            packet["datasets"].append(
                {**copy.deepcopy(packet["datasets"][0]), "dataset_id": "other"}
            )
            b["dataset_id"] = "other"
    fixtures.save_json(original_path, original)
    fixtures.save_json(path, prepared)
    case["source"]["inputs"]["metadata_manifest"] = fixtures.pin(tmp_path, original_path)
    case["plan"]["prepared_manifest"] = fixtures.pin(tmp_path, path)
    change_report(case)
    pair = run(case)["candidates"][0]
    assert not pair["cross_assigned_uses"]
    assert pair["same_declared_local_subject"] is (
        True if relation == "same_local" else False if relation == "different_local" else None
    )
    assert pair["same_declared_linked_subject"] is (True if relation == "same_linked" else None)


@pytest.mark.parametrize(
    "field", ["age", "processing", "use", "subject_id", "exposure", "order", "omitted"]
)
def test_changed_k5_or_omitted_ledger_is_rejected(tmp_path, field):
    case = make_case(tmp_path)
    path = tmp_path / fixtures.OUTPUT / "prepared-manifest.json"
    value = case["prepared"]
    if field == "age":
        value["records"][0][field] = data.metadata.age_label("unknown")
    elif field == "processing":
        value["records"][0][field] = {"status": "not_checked", "reason": None}
    elif field == "use":
        value["records"][0][field] = "unassigned"
    elif field == "subject_id":
        value["records"][0][field] = "changed"
    elif field == "exposure":
        value["records"][0][field]["preprocessing"] = "unknown"
    elif field == "order":
        value["records"].reverse()
    else:
        value["records"].pop()
    fixtures.save_json(path, value)
    case["plan"]["prepared_manifest"] = fixtures.pin(tmp_path, path)
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize(
    "mutation",
    ["algorithm", "limits", "environment", "bool_limit", "extra", "schema", "reserve", "sources"],
)
def test_invalid_plan_rejected_before_output(tmp_path, mutation):
    case = make_case(tmp_path)
    plan = case["plan"]
    if mutation == "algorithm":
        plan["fingerprint_contract"]["algorithm"]["max_horizontal_hamming"] = 9
    elif mutation == "limits":
        plan["fingerprint_contract"]["limits"]["max_images"] = 32
    elif mutation == "environment":
        plan["fingerprint_contract"]["environment"]["python_version"] = "3.12"
    elif mutation == "bool_limit":
        plan["fingerprint_contract"]["limits"]["frames"] = True
    elif mutation == "extra":
        plan["omit_failures"] = True
    elif mutation == "schema":
        plan["schema_id"] = data.retrieval.PROTOCOL
    elif mutation == "reserve":
        plan["reserve_bytes"] = True
    else:
        plan["algorithm_sources"].pop()
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_runtime_environment_drift_rejects(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setattr(data, "PILLOW_VERSION", "0")
    with pytest.raises(ValueError, match="ENVIRONMENT_MISMATCH"):
        run(case)


def test_repinned_algorithm_must_match_running_code(tmp_path):
    case = make_case(tmp_path)
    path = tmp_path / data.ALGORITHM_SOURCES[0]
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    case["plan"]["algorithm_sources"][0] = fixtures.pin(tmp_path, path)
    with pytest.raises(ValueError, match="RUNNING_ALGORITHM_MISMATCH"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_full_32_image_bound_preserves_all_496_pairs(tmp_path):
    with Image.new("RGB", (2, 2), (10, 20, 30)) as image:
        raw = encoded(image)
    report = run(make_case(tmp_path, [raw] * 32))
    assert report["status"] == "passed"
    assert report["summary"]["requested_pairs"] == report["summary"]["candidate_pairs"] == 496
    assert len(report["pair_ledger"]) == 496
    assert report["components"][0]["image_indices"] == list(range(32))
    assert all(len(c["matched_view_pairs"]) == 4 for c in report["candidates"])


@pytest.mark.parametrize("kind", ["normalized", "report", "prepared", "original", "algorithm"])
def test_pinned_inputs_drift(tmp_path, kind):
    case = make_case(tmp_path)
    paths = {
        "normalized": case["source"]["records"][0]["normalized"]["path"],
        "report": case["plan"]["preparation_report"]["path"],
        "prepared": case["plan"]["prepared_manifest"]["path"],
        "original": case["source"]["inputs"]["metadata_manifest"]["path"],
        "algorithm": data.ALGORITHM_SOURCES[0],
    }
    path = tmp_path / paths[kind]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    path.write_bytes(path.read_bytes() + b" ")
    if kind == "normalized":
        report = run(case)
        assert report["summary"]["failed_images"] == 1
        assert not report["inputs_stable"]
        assert report["records"][0]["error_code"] == "NORMALIZED_PIN_MISMATCH"
        assert report["summary"]["uncomparable_pairs"] == 2
    else:
        with pytest.raises(ValueError, match="PIN_MISMATCH"):
            run(case)
        assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("kind", ["normalized", "report", "algorithm", "plan"])
def test_late_changes_fail_after_comparison_and_stale_edges_are_removed(
    tmp_path, monkeypatch, kind
):
    case = make_case(tmp_path)
    original_pairs = data._pairs

    def changed(rows, features):
        result = original_pairs(rows, features)
        name = {
            "normalized": case["source"]["records"][0]["normalized"]["path"],
            "report": case["plan"]["preparation_report"]["path"],
            "algorithm": data.ALGORITHM_SOURCES[0],
            "plan": "output/research/input/screen-plan.json",
        }[kind]
        path = tmp_path / name
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(data, "_pairs", changed)
    report = run(case)
    assert report["status"] == "failed" and not report["inputs_stable"]
    if kind == "normalized":
        assert report["records"][0]["error_code"] == "SOURCE_CHANGED_AFTER_COMPARISON"
        assert report["summary"]["candidate_pairs"] == 1
        assert all(0 not in (c["left_index"], c["right_index"]) for c in report["candidates"])
        assert all(0 not in g["image_indices"] for g in report["exact_groups"])
        assert report["summary"]["uncomparable_pairs"] == 2
        assert report["components"][0]["image_indices"] == [1, 2]
        assert report["pair_ledger"][2]["candidate_id"] == report["candidates"][0]["candidate_id"]


@pytest.mark.parametrize("problem", ["size", "mode", "bad_image", "exif", "large_pin"])
def test_bad_normalized_record_remains_in_denominator(tmp_path, problem):
    case = make_case(tmp_path)
    row = case["source"]["records"][0]
    path = tmp_path / row["normalized"]["path"]
    if problem == "size":
        row["normalized_size"] = [1, 1]
    elif problem == "mode":
        row["normalized_mode"] = "L"
    elif problem == "large_pin":
        row["normalized"]["bytes"] = data.retrieval.MAX_IMAGE_BYTES + 1
    else:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
        if problem == "bad_image":
            path.write_bytes(b"not a PNG")
        else:
            with raster() as image:
                exif = Image.Exif()
                exif[274] = 6
                path.write_bytes(encoded(image, exif=exif))
        row["normalized"] = fixtures.pin(tmp_path, path)
    change_report(case)
    report = run(case)
    assert report["status"] == "failed"
    assert report["summary"]["failed_images"] == 1
    assert report["summary"]["uncomparable_pairs"] == 2
    assert not report["records"][0]["read_attempted"] if problem == "large_pin" else True


@pytest.mark.parametrize("output", ["data/review", "output/research", "output/research/../escape"])
def test_output_scope_and_existing_evidence_preserved(tmp_path, output):
    case = make_case(tmp_path)
    with pytest.raises(ValueError):
        run(case, output)
    first = run(case)
    saved = (tmp_path / first["receipt"]).read_bytes()
    with pytest.raises(ValueError, match="OUTPUT_MUST_BE_NEW"):
        run(case)
    assert (tmp_path / first["receipt"]).read_bytes() == saved


def test_disk_budget_rejects_before_output(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(data.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(ValueError, match="INSUFFICIENT_SPACE"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_plan_hash_and_duplicate_json_keys_reject(tmp_path):
    case = make_case(tmp_path)
    name, digest = freeze(case)
    with pytest.raises(ValueError, match="PLAN_SHA256_MISMATCH"):
        data.screen(tmp_path, name, "0" * 64, OUTPUT)
    path = tmp_path / name
    raw = path.read_bytes().replace(b'"plan_id":', b'"plan_id":"duplicate","plan_id":')
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="DUPLICATE_JSON_KEY"):
        data.screen(tmp_path, name, hashlib.sha256(raw).hexdigest(), OUTPUT)


@pytest.mark.parametrize(
    "bad_image,wrong_hash,expected", [(False, False, 0), (True, False, 1), (False, True, 2)]
)
def test_cli_success_failure_and_input_rejection(tmp_path, bad_image, wrong_hash, expected):
    with raster() as image:
        raw = encoded(image)
    case = make_case(tmp_path, [raw, b"bad" if bad_image else raw])
    name, digest = freeze(case)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "preprocessing.duplicate_screening",
            "--root",
            str(tmp_path),
            "--plan",
            name,
            "--plan-sha256",
            "0" * 64 if wrong_hash else digest,
            "--output-dir",
            OUTPUT,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected and not result.stderr
    response = json.loads(result.stdout)
    assert all(response[k] is False for k in data.acquisition.FLAGS)
    assert (tmp_path / OUTPUT / "report.json").exists() is (expected != 2)
