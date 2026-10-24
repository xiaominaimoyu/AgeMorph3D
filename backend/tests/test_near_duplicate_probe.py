"""Synthetic duplicate candidates remain an unaccepted similarity review queue."""

import hashlib
import importlib.util
import io
import json
import struct
from pathlib import Path

import pytest
from PIL import Image, ImageFile, ImageOps

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "near_duplicate_probe", ROOT / "tools/near_duplicate_probe.py"
)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)
_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "_near_duplicate_fixtures", Path(__file__).with_name("test_evaluation_readiness_probe.py")
)
fixtures = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(fixtures)


def encoded(image, format="PNG", **kwargs):
    output = io.BytesIO()
    image.save(output, format=format, **kwargs)
    return output.getvalue()


def gradient(reverse=False):
    image = Image.new("RGB", (16, 16))
    image.putdata(
        [(y * 15 if not reverse else 255 - y * 15,) * 3 for y in range(16) for _ in range(16)]
    )
    return image


def replace_image(case, index, raw, suffix="png"):
    path = case["root"] / f"data/images/{index}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    case["manifest"]["adult_images"][index].update(
        path=path.relative_to(case["root"]).as_posix(),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


@pytest.fixture
def case(tmp_path):
    case = fixtures.case.__wrapped__(tmp_path)
    for name in probe.SOURCES[2:]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    case["near_protocol"] = json.loads(
        (ROOT / "docs/near-duplicate-v1.json").read_text(encoding="utf-8")
    )
    for index, color in enumerate(("red", "green", "blue")):
        replace_image(case, index, encoded(Image.new("RGB", (4, 4), color)))
    return case


def freeze(case):
    fixtures.freeze(case)
    root = case["root"]
    manifest_pin = fixtures.write(root, "output/research/n0/manifest.json", case["manifest"])
    return fixtures.write(
        root,
        "output/research/input/near-plan.json",
        {
            "protocol_id": probe.PROTOCOL,
            "protocol": fixtures.write(root, "docs/near-protocol.json", case["near_protocol"]),
            "n0_manifest": manifest_pin,
            "age_protocol": fixtures.pin(root / "docs/protocol.json", root),
            "source_files": [fixtures.pin(root / name, root) for name in probe.SOURCES],
            "environment": dict(probe.ENVIRONMENT),
        },
    )


def run(case):
    plan = freeze(case)
    return probe.build_report(case["root"], case["root"] / plan["path"])


def fake_features(horizontal, vertical):
    view = {
        "horizontal": horizontal,
        "vertical": vertical,
        "pixel_sha256": f"{horizontal ^ vertical:064x}",
        "gray32": bytes(1024),
    }
    return {"width": 1, "height": 1, "views": {"original": dict(view), "mirror": dict(view)}}


def test_fixed_dhash_direction_and_msb_bit_order():
    image = Image.new("L", (9, 9))
    image.putdata([x * 20 + y * 2 for y in range(9) for x in range(9)])
    assert probe._dhash(image, True) == 0xFFFFFFFFFFFFFFFF
    assert probe._dhash(image, False) == 0xFFFFFFFFFFFFFFFF
    reverse = ImageOps.invert(image)
    assert probe._dhash(reverse, True) == probe._dhash(reverse, False) == 0
    exact_grid = Image.new("L", (9, 8))
    exact_grid.putdata([0, 1, 1, 1, 1, 1, 1, 1, 1] + [0] * 63)
    assert probe._dhash(exact_grid, True) == 1 << 63
    vertical_grid = Image.new("L", (8, 9))
    vertical_grid.putdata([0] * 8 + [1] + [0] * 63)
    assert probe._dhash(vertical_grid, False) == 1 << 63


def test_dimension_bound_pixel_hash_vector():
    image = Image.new("RGB", (2, 3), (1, 2, 3))
    expected = hashlib.sha256(
        b"agemorph3d-rgb-v1\0" + struct.pack(">II", 2, 3) + b"RGB\0" + bytes([1, 2, 3]) * 6
    ).hexdigest()
    assert probe._pixel_hash(image) == expected
    assert probe._pixel_hash(Image.new("RGB", (3, 2), (1, 2, 3))) != expected


def test_threshold_eight_is_inclusive_and_nine_excluded():
    left = fake_features(0, 0)
    assert len(probe._matches(left, fake_features((1 << 8) - 1, (1 << 8) - 1))[0]) == 4
    assert probe._matches(left, fake_features((1 << 9) - 1, 0))[0] == []


def test_horizontal_and_vertical_cannot_be_combined_from_different_views():
    left = fake_features(0, 0)
    right = fake_features(0, (1 << 9) - 1)
    right["views"]["mirror"].update(horizontal=(1 << 9) - 1, vertical=0)
    assert probe._matches(left, right)[0] == []


def test_mirror_view_matches_corrected_original_pixels():
    image = Image.new("RGB", (16, 16))
    image.putdata([(x * 15, y * 15, (x + y) * 7) for y in range(16) for x in range(16)])
    left = probe._decode(encoded(image))
    right = probe._decode(encoded(ImageOps.mirror(image)))
    hits, exact = probe._matches(left, right)
    assert {"left_view": "original", "right_view": "mirror"} in exact
    assert any(hit["left_view"] == "original" and hit["right_view"] == "mirror" for hit in hits)


def test_exif_transpose_happens_before_features():
    image = Image.new("RGB", (3, 2))
    image.putdata([(x * 80, y * 100, 40) for y in range(2) for x in range(3)])
    exif = Image.Exif()
    exif[274] = 6
    raw = encoded(image, "JPEG", exif=exif, quality=100, subsampling=0)
    result = probe._decode(raw)
    assert (result["width"], result["height"]) == (2, 3)
    with Image.open(io.BytesIO(raw)) as source:
        expected = ImageOps.exif_transpose(source).convert("RGB")
        assert result["views"]["original"]["pixel_sha256"] == probe._pixel_hash(expected)


def test_different_encodings_same_pixels_are_separate_exact_pixel_evidence(case):
    image = gradient()
    replace_image(case, 0, encoded(image, compress_level=0))
    replace_image(case, 1, encoded(image, compress_level=9))
    report = run(case)
    candidate = next(
        edge
        for edge in report["candidates"]
        if edge["left_index"] == 0 and edge["right_index"] == 1
    )
    assert candidate["same_file_sha256"] is False
    assert len(candidate["equal_pixel_view_pairs"]) == 4
    assert candidate["cross_group"] and candidate["cross_identity"]


def test_no_candidates_does_not_accept_absence_of_leakage():
    assert probe._matches(fake_features(0, 0), fake_features((1 << 64) - 1, (1 << 64) - 1))[0] == []


def test_nontransitive_components_preserve_only_observed_edges():
    candidates = [
        {"candidate_id": 0, "left_index": 0, "right_index": 1},
        {"candidate_id": 1, "left_index": 1, "right_index": 2},
    ]
    component = probe._components(candidates)[0]
    assert component["image_indices"] == [0, 1, 2]
    assert [(edge["left_index"], edge["right_index"]) for edge in component["edges"]] == [
        (0, 1),
        (1, 2),
    ]
    assert probe._matches(fake_features(0, 0), fake_features((1 << 8) - 1, 0))[0]
    assert probe._matches(fake_features((1 << 8) - 1, 0), fake_features((1 << 16) - 1, 0))[0]
    assert not probe._matches(fake_features(0, 0), fake_features((1 << 16) - 1, 0))[0]


def test_hash_failure_never_decodes_and_retains_pair_denominator(case, monkeypatch):
    case["manifest"]["adult_images"][0]["sha256"] = "a" * 64
    original = probe._decode
    decoded = []

    def counted(raw):
        decoded.append(raw)
        return original(raw)

    monkeypatch.setattr(probe, "_decode", counted)
    report = run(case)
    assert len(decoded) == 2
    assert report["integrity_status"] == "failed"
    assert report["records"][0]["status"] == "hash_or_size_mismatch"
    assert report["records"][0]["final_source_check"]["sha256"] is not None
    assert report["pair_counts"] == {"requested": 3, "comparable": 1, "uncomparable": 2}


@pytest.mark.parametrize(
    "failure",
    ["bad_image", "truncated_image", "multiple_frames", "pixel_limit", "not_verified_size_limit"],
)
def test_failed_images_remain_in_requested_count(case, failure):
    if failure == "bad_image":
        raw = b"not an image"
    elif failure == "truncated_image":
        raw = encoded(Image.new("RGB", (32, 32)), "JPEG")[:-10]
    elif failure == "multiple_frames":
        output = io.BytesIO()
        Image.new("RGB", (4, 4), "red").save(
            output, format="PNG", save_all=True, append_images=[Image.new("RGB", (4, 4), "blue")]
        )
        raw = output.getvalue()
    elif failure == "pixel_limit":
        raw = encoded(Image.new("L", (4001, 4000)))
    else:
        raw = b"0" * (probe.MAX_IMAGE_BYTES + 1)
    replace_image(case, 0, raw)
    report = run(case)
    assert report["records"][0]["status"] == failure
    assert report["image_counts"] == {"requested": 3, "successful": 2, "failed": 1}
    assert report["pair_counts"]["uncomparable"] == 2
    if failure == "not_verified_size_limit":
        assert report["integrity_status"] == "failed"
        assert report["records"][0]["final_source_check"]["sha256"] is None


def test_source_image_change_is_retained_and_excluded(case, monkeypatch):
    original = probe._decode
    changed = False

    def mutate(raw):
        nonlocal changed
        result = original(raw)
        if not changed:
            changed = True
            path = case["root"] / case["manifest"]["adult_images"][0]["path"]
            path.write_bytes(b"changed original")
        return result

    monkeypatch.setattr(probe, "_decode", mutate)
    report = run(case)
    assert report["integrity_status"] == "failed"
    assert report["records"][0]["status"] == "source_changed"
    assert report["image_counts"]["successful"] == 2


def test_image_change_during_candidate_analysis_is_caught_after_analysis(case, monkeypatch):
    plan = freeze(case)
    original = probe._candidates

    def mutate(rows, features):
        candidates = original(rows, features)
        assert len(candidates) == 3
        path = case["root"] / rows[0]["path"]
        path.write_bytes(b"source changed during candidate analysis")
        return candidates

    monkeypatch.setattr(probe, "_candidates", mutate)
    assert (
        probe.main(
            [
                "--root",
                str(case["root"]),
                "--study-plan",
                plan["path"],
                "--output-dir",
                "output/research/during-analysis",
            ]
        )
        == 1
    )
    report = json.loads(
        (case["root"] / "output/research/during-analysis/report.json").read_text(encoding="utf-8")
    )
    assert report["integrity_status"] == "failed"
    assert report["screening_status"] == "incomplete"
    assert report["analysis_image_count_before_final_source_check"] == 3
    assert report["image_counts"] == {"requested": 3, "successful": 2, "failed": 1}
    assert report["pair_counts"] == {"requested": 3, "comparable": 1, "uncomparable": 2}
    assert report["records"][0]["status_before_source_change"] == "ok"
    assert report["records"][0]["source_changed"] is True
    assert len(report["candidates"]) == 1
    assert all(0 not in (edge["left_index"], edge["right_index"]) for edge in report["candidates"])
    assert all(0 not in component["image_indices"] for component in report["components"])


def test_metadata_source_drift_rejects_whole_publication(case, monkeypatch):
    plan = freeze(case)
    original = probe._decode
    changed = False

    def mutate(raw):
        nonlocal changed
        result = original(raw)
        if not changed:
            changed = True
            (case["root"] / probe.SOURCES[3]).write_text("# changed", encoding="utf-8")
        return result

    monkeypatch.setattr(probe, "_decode", mutate)
    with pytest.raises(ValueError, match="pin mismatch"):
        probe.build_report(case["root"], case["root"] / plan["path"])


@pytest.mark.parametrize(
    "mutation",
    [
        "traversal",
        "duplicate_path",
        "algorithm",
        "boolean_size",
        "extra_key",
        "environment",
        "missing_source",
        "duplicate_key",
    ],
)
def test_invalid_plan_or_provenance_rejected_before_decode(case, monkeypatch, mutation):
    if mutation == "traversal":
        case["manifest"]["adult_images"][0]["path"] = "../outside.png"
    elif mutation == "duplicate_path":
        case["manifest"]["adult_images"][1]["path"] = case["manifest"]["adult_images"][0]["path"]
    elif mutation == "algorithm":
        case["near_protocol"]["algorithm"]["max_horizontal_hamming"] = 9
    plan_pin = freeze(case)
    path = case["root"] / plan_pin["path"]
    plan = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "boolean_size":
        plan["protocol"]["bytes"] = True
    elif mutation == "extra_key":
        plan["quality_passed"] = True
    elif mutation == "environment":
        plan["environment"]["pillow_version"] = "0.0.0"
    elif mutation == "missing_source":
        plan["source_files"].pop()
    if mutation == "duplicate_key":
        path.write_text('{"protocol_id":1,"protocol_id":2}', encoding="utf-8")
    else:
        fixtures.write(case["root"], plan_pin["path"], plan)

    def forbidden(_):
        raise AssertionError("Bad input must not decode a photograph.")

    monkeypatch.setattr(probe, "_decode", forbidden)
    with pytest.raises(ValueError):
        probe.build_report(case["root"], path)


def test_cli_json_only_rejects_existing_output_and_keeps_false_flags(case):
    plan = freeze(case)
    args = [
        "--root",
        str(case["root"]),
        "--study-plan",
        plan["path"],
        "--output-dir",
        "output/research/near",
    ]
    before = (Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES)
    assert probe.main(args) == 0
    output = case["root"] / "output/research/near"
    assert [path.name for path in output.iterdir()] == ["report.json"]
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert all(report[field] is False for field in probe.FALSE_FLAGS)
    assert report["automatic_original_image_feature_reading_disclosed"] is True
    assert before == (Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES)
    assert probe.main(args) == 1


def test_cli_failed_image_retains_report_and_returns_one(case):
    replace_image(case, 0, b"broken")
    plan = freeze(case)
    assert (
        probe.main(
            [
                "--root",
                str(case["root"]),
                "--study-plan",
                plan["path"],
                "--output-dir",
                "output/research/failed",
            ]
        )
        == 1
    )
    assert (case["root"] / "output/research/failed/report.json").is_file()


def test_same_file_duplicate_and_large_mae_are_kept_as_candidate():
    left, right = fake_features(0, 0), fake_features(0, 0)
    for view in right["views"].values():
        view["gray32"] = bytes([255]) * 1024
    rows = [
        {
            "path": name,
            "group": "development",
            "subject_id": "001",
            "source_age": age,
            "sha256": "a" * 64,
        }
        for name, age in (("left.png", 20), ("right.png", 21))
    ]
    edge = probe._candidates(rows, {0: left, 1: right})[0]
    assert edge["same_file_sha256"] is True
    assert len(edge["matched_view_pairs"]) == 4
    assert all(hit["gray32_mae"] == 1 for hit in edge["matched_view_pairs"])
    assert edge["label_age_difference"] == 1


def test_output_outside_research_is_rejected(case):
    plan = freeze(case)
    assert (
        probe.main(
            ["--root", str(case["root"]), "--study-plan", plan["path"], "--output-dir", "docs/near"]
        )
        == 1
    )
    assert not (case["root"] / "docs/near").exists()
