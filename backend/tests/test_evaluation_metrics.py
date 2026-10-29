"""Frozen-denominator, paired-estimand, explicit-NME and offline CLI regression."""

import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from agemorph3d import age_statistics
from agemorph3d import evaluation_metrics as metrics

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "evaluation_metrics_probe", ROOT / "tools/evaluation_metrics_probe.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.fixture
def packet():
    requests = [
        {"request_id": key, "subject_id": subject, "stratum": group}
        for key, subject, group in [
            ("r1", "person:A", "front"),
            ("r2", "person:A", "side"),
            ("r3", "person:B", "front"),
            ("r4", "person:C", "side"),
        ]
    ]
    values = {
        "baseline": [1, 3, 10, None],
        "candidate": [2, None, 8, None],
    }
    variants = []
    for name, rows in values.items():
        variants.append(
            {
                "name": name,
                "records": [
                    {
                        "request_id": request["request_id"],
                        "status": "ok" if value is not None else "failed",
                        "value": value,
                        "error_code": None if value is not None else "NO_FACE",
                    }
                    for request, value in zip(requests, rows, strict=True)
                ],
            }
        )
    return {
        "schema_version": 1,
        "protocol_id": metrics.PROTOCOL,
        "research_only": True,
        "metric": {
            "id": "synthetic_geometry_proxy",
            "unit": "source_canonical",
            "direction": "lower",
            "normalization": "unchanged source frame",
            "quality_threshold": None,
        },
        "bootstrap": {"seed": 20261029, "samples": 40},
        "requests": requests,
        "variants": variants,
        "provenance": [],
    }


def test_full_denominators_identity_weights_and_common_set_delta(packet, monkeypatch):
    original = copy.deepcopy(packet)
    calls = []
    existing = age_statistics.aggregate_identity_metrics

    def delegated(*args, **kwargs):
        calls.append(1)
        return existing(*args, **kwargs)

    monkeypatch.setattr(metrics, "aggregate_identity_metrics", delegated)
    report = metrics.summarize_study(packet)
    assert calls and packet == original
    left = report["variants"]["baseline"]
    right = report["variants"]["candidate"]
    assert (
        left["summary"]["requests"] == 4
        and left["summary"]["successes"] == 3
        and left["summary"]["failures"] == 1
    )
    assert left["summary"]["macro"]["value"]["mean"] == 6.0
    assert left["summary"]["macro"]["value"]["mean"] != 14 / 3
    assert left["summary"]["identities_without_valid_metrics"] == ["person:C"]
    assert right["summary"]["macro"]["value"]["mean"] == 5.0
    comparison = report["comparisons"][0]
    assert comparison["request_sets"] == {
        "common_success": ["r1", "r3"],
        "left_only_success": ["r2"],
        "right_only_success": [],
        "both_failed": ["r4"],
    }
    assert comparison["all_requested_pairs"] == 4
    assert comparison["paired_summary"]["macro"]["value"]["mean"] == -0.5
    assert comparison["paired_summary"]["macro"]["value"]["mean"] != 5 - 6
    assert comparison["identities_without_common_success"] == ["person:C"]
    assert comparison["strata"]["side"]["macro"]["value"]["mean"] is None
    assert comparison["strata"]["front"]["macro"]["value"]["identities"] == 2
    assert right["failure_codes"] == {"NO_FACE": 2}
    assert all(report[k] is False for k in metrics.FLAGS)


def test_all_failed_single_identity_and_one_variant_keep_null_not_zero(packet):
    for variant in packet["variants"]:
        for row in variant["records"]:
            row.update(status="failed", value=None, error_code="NO_FACE")
    report = metrics.summarize_study(packet)
    for variant in report["variants"].values():
        summary = variant["summary"]
        assert summary["requests"] == summary["failures"] == 4
        assert summary["macro"]["value"] == {
            "identities": 0,
            "observations": 0,
            "mean": None,
            "median": None,
            "ci95": None,
        }
    assert report["comparisons"][0]["request_sets"]["both_failed"] == ["r1", "r2", "r3", "r4"]
    assert report["comparisons"][0]["paired_summary"]["requests"] == 0
    packet["variants"] = packet["variants"][:1]
    for row in packet["requests"]:
        row["subject_id"] = "one"
    packet["variants"][0]["records"][0].update(status="ok", value=2.5, error_code=None)
    single = metrics.summarize_study(packet)
    assert single["comparisons"] == []
    assert single["variants"]["baseline"]["summary"]["macro"]["value"]["ci95"] is None


def test_pair_partition_includes_right_only_success_and_all_failed_subjects(packet):
    packet["variants"][0]["records"][0].update(status="failed", value=None, error_code="NO_FACE")
    report = metrics.summarize_study(packet)
    comparison = report["comparisons"][0]
    assert comparison["request_sets"] == {
        "common_success": ["r3"],
        "left_only_success": ["r2"],
        "right_only_success": ["r1"],
        "both_failed": ["r4"],
    }
    assert sum(map(len, comparison["request_sets"].values())) == 4
    assert comparison["paired_summary"]["macro"]["value"]["mean"] == -2.0
    assert comparison["paired_summary"]["macro"]["value"]["ci95"] is None
    assert comparison["identities_without_common_success"] == ["person:A", "person:C"]


def test_order_independence_and_higher_direction_do_not_change_delta_sign(packet):
    before = metrics.summarize_study(packet)
    packet["requests"].reverse()
    for variant in packet["variants"]:
        variant["records"].reverse()
    packet["metric"]["direction"] = "higher"
    after = metrics.summarize_study(packet)
    assert after["comparisons"] == before["comparisons"]
    assert after["variants"] == before["variants"]
    assert after["metric"]["direction"] == "higher" and after["quality_accepted"] is False


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["variants"][0]["records"].pop(),
        lambda p: p["variants"][0]["records"].__setitem__(1, p["variants"][0]["records"][0]),
        lambda p: p["variants"][0]["records"][0].update(request_id="not requested"),
        lambda p: p["requests"].__setitem__(1, p["requests"][0]),
        lambda p: p["requests"][0].update(subject_id=None),
        lambda p: p["variants"][0]["records"][0].update(value=True),
        lambda p: p["variants"][0]["records"][0].update(value=float("nan")),
        lambda p: p["variants"][0]["records"][0].update(value=float("inf")),
        lambda p: p["variants"][0]["records"][0].update(value=10**10000),
        lambda p: p["variants"][0]["records"][0].update(error_code="NO_FACE"),
        lambda p: p["variants"][0]["records"][3].update(value=0),
        lambda p: p["variants"][0]["records"][3].update(error_code=None),
        lambda p: p["variants"][0]["records"][3].update(status="NO_FACE"),
        lambda p: p["variants"].append(copy.deepcopy(p["variants"][0])),
        lambda p: p.update(schema_version=True),
        lambda p: p.update(research_only=False),
        lambda p: p.update(quality_accepted=True),
        lambda p: p["metric"].update(quality_threshold=0.1),
        lambda p: p["bootstrap"].update(seed=True),
        lambda p: p["bootstrap"].update(samples=0),
        lambda p: p["bootstrap"].update(samples=10001),
        lambda p: p.update(
            provenance=[{"path": "../private.json", "bytes": 2, "sha256": "a" * 64}]
        ),
    ],
)
def test_missing_results_invalid_values_and_qualification_claims_rejected(packet, change):
    change(packet)
    with pytest.raises(ValueError):
        metrics.summarize_study(packet)


def test_resource_budgets_and_provenance_duplicates_are_enforced(packet, monkeypatch):
    monkeypatch.setattr(metrics, "MAX_BOOTSTRAP_WORK", 1)
    with pytest.raises(ValueError, match="work budget"):
        metrics.summarize_study(packet)
    monkeypatch.undo()
    pin = {"path": "output/research/old.json", "bytes": 2, "sha256": "a" * 64}
    packet["provenance"] = [pin, pin]
    with pytest.raises(ValueError):
        metrics.summarize_study(packet)


def landmarks():
    prediction = {
        "point_ids": ["eye", "mouth", "unobserved"],
        "points": [[3, 4], [0, 2], None],
        "coordinate_frame": "image_EXIF_corrected_pixels",
    }
    reference = {
        "point_ids": ["eye", "mouth", "unobserved"],
        "points": [[0, 0], [0, 0], None],
        "coordinate_frame": "image_EXIF_corrected_pixels",
    }
    return (
        prediction,
        reference,
        [True, True, False],
        {"id": "explicit-reference-distance", "distance": 10},
    )


def test_nme_explicit_visibility_point_order_normalization_and_scale():
    args = landmarks()
    original = copy.deepcopy(args)
    result = metrics.nme_2d(*args)
    assert (
        result["ratio"] == 0.35
        and result["visible_points"] == 2
        and result["requested_points"] == 3
    )
    assert result["benchmark_equivalence_verified"] is False and args == original
    for group in args[:2]:
        for point in group["points"]:
            if point is not None:
                point[:] = [value * 100 for value in point]
    args[3]["distance"] *= 100
    assert metrics.nme_2d(*args)["ratio"] == 0.35


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a[0]["point_ids"].reverse(),
        lambda a: a[0].update(coordinate_frame="another"),
        lambda a: a[2].__setitem__(0, 1),
        lambda a: a[2].__setitem__(1, False) or a[2].__setitem__(0, False),
        lambda a: a[0]["points"].__setitem__(0, None),
        lambda a: a[0]["points"][0].__setitem__(0, True),
        lambda a: a[0]["points"].__setitem__(2, [float("nan"), 0]),
        lambda a: a[3].update(distance=0),
        lambda a: a[3].update(distance=-1),
        lambda a: a[3].update(distance=True),
        lambda a: a[3].update(distance=float("inf")),
        lambda a: a[0]["point_ids"].__setitem__(1, "eye"),
    ],
)
def test_nme_does_not_impute_unknowns_or_accept_incompatible_geometry(change):
    args = landmarks()
    change(args)
    with pytest.raises(ValueError):
        metrics.nme_2d(*args)


def write_packet(root, packet):
    p = root / "packet.json"
    raw = (json.dumps(packet, allow_nan=False) + "\n").encode()
    p.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("bad", [b'{"a":1,"a":2}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_cli_parser_rejects_ambiguous_json(bad):
    with pytest.raises(ValueError):
        probe._json(bad)


def test_cli_export_reads_only_packet_and_sources_and_refuses_overwrite(
    tmp_path, packet, monkeypatch
):
    digest = write_packet(tmp_path, packet)
    original = Path.open
    reads = []

    def opened(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if "r" in mode:
            reads.append(path.resolve())
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    report = probe.export(tmp_path, "packet.json", digest, "output/research/run")
    assert report["status"] == "completed_with_failures"
    assert set(reads) == {(tmp_path / "packet.json").resolve(), *probe.SOURCES}
    with pytest.raises(FileExistsError):
        probe.export(tmp_path, "packet.json", digest, "output/research/run")
    assert (
        json.loads((tmp_path / "output/research/run/report.json").read_bytes())["requested_pairs"]
        == 4
    )


def test_cli_drift_cleanup_preserves_unowned_files(tmp_path, packet, monkeypatch):
    digest = write_packet(tmp_path, packet)
    original = probe._read
    calls = 0

    def drift(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            (tmp_path / "output/research/run/other.txt").write_bytes(b"keep")
            path.write_bytes(b"changed")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(probe, "_read", drift)
    with pytest.raises(ValueError):
        probe.export(tmp_path, "packet.json", digest, "output/research/run")
    assert sorted(p.name for p in (tmp_path / "output/research/run").iterdir()) == ["other.txt"]


def test_cli_input_output_budgets_and_external_paths(tmp_path, packet, monkeypatch):
    digest = write_packet(tmp_path, packet)
    with pytest.raises(ValueError):
        probe._read(tmp_path / "packet.json", 1)
    original = Path.open
    monkeypatch.setattr(
        Path,
        "open",
        lambda p, *a, **k: (
            io.BytesIO(b"123456") if p == tmp_path / "packet.json" else original(p, *a, **k)
        ),
    )
    with pytest.raises(ValueError):
        probe._read(tmp_path / "packet.json", 5)
    monkeypatch.undo()
    monkeypatch.setattr(probe, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="Output JSON"):
        probe.export(tmp_path, "packet.json", digest, "output/research/run")
    assert not (tmp_path / "output/research/run").exists()
    for name in ("../private.json", "C:/private.json", "output//bad", "output\\bad"):
        with pytest.raises(ValueError):
            probe._path(tmp_path, name)


@pytest.mark.parametrize(("mode", "expected"), [("success", 0), ("failures", 1), ("invalid", 2)])
def test_actual_cli_process_exit_and_closed_flags(tmp_path, packet, mode, expected):
    package = tmp_path / "agemorph3d"
    package.mkdir()
    (package / "__init__.py").write_bytes(b"")
    for module in (metrics, age_statistics):
        (package / Path(module.__file__).name).write_bytes(Path(module.__file__).read_bytes())
    tool = tmp_path / "tools/evaluation_metrics_probe.py"
    tool.parent.mkdir()
    tool.write_bytes((ROOT / "tools/evaluation_metrics_probe.py").read_bytes())
    if mode == "success":
        for variant in packet["variants"]:
            for row in variant["records"]:
                row.update(status="ok", value=1.0, error_code=None)
    if mode == "invalid":
        packet["variants"][0]["records"].pop()
    digest = write_packet(tmp_path, packet)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(tool),
            "--packet",
            "packet.json",
            "--sha256",
            digest,
            "--output-dir",
            "output/research/result",
        ],
        capture_output=True,
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path)),
    )
    assert result.returncode == expected, result.stderr
    output = tmp_path / "output/research/result"
    if expected == 2:
        assert not output.exists() and json.loads(result.stderr)["status"] == "invalid_input"
    else:
        report = json.loads((output / "report.json").read_bytes())
        assert report["requested_pairs"] == 4 and all(report[k] is False for k in metrics.FLAGS)
