"""Synthetic workbench serialization, evidence gates and publication boundaries."""

import base64
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools/mask_review_workbench.py"
_SPEC = importlib.util.spec_from_file_location("mask_review_workbench", _PATH)
workbench = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(workbench)


def template():
    return (
        '<!doctype html><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "connect-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; "
        "script-src 'sha256-__WORKBENCH_SCRIPT_HASH__'; base-uri 'none'; form-action 'none'\">"
        '<script id="case-data" type="application/json">__WORKBENCH_DATA__</script>'
        '<script type="module">__WORKBENCH_SCRIPT__</script>'
    )


def synthetic_vectors():
    return {
        "texel_rows_columns": np.array([[0, 0], [1, 2]], dtype="<i4"),
        "face_owner": np.array([0, 17], dtype="<i4"),
        "barycentric": np.array([[0.25, 0.25, 0.5], [0, 1, 0]], dtype="<f8"),
        "target_xyz": np.array([[0.125, 1.75, -3], [2**-40, -0.0, 11]], dtype="<f8"),
        "source_canonical_xyz": np.asfortranarray(
            [[0.0123456789012345, 2**-45, -0.125], [-1.5, 0, 7.75]], dtype="<f8"
        ),
        "region_bits": np.array([1, 15], dtype="u1"),
        "rejection_partition": np.array([0, 2], dtype="u1"),
    }


def publication_fixture():
    samples = [f"synthetic-{index:02d}" for index in range(12)]
    pages = {"index.html": b"<!doctype html><title>index</title>"}
    pages.update({f"cases/{sample}.html": sample.encode() for sample in samples})
    report = {
        "records": [
            {"sample_id": sample, "status": "ok", "artifacts": {"page": sample}}
            for sample in samples
        ],
        "summary": {"requested_targets": 12, "all_requested_verified": True},
    }
    return pages, report


def evidence_fixture(monkeypatch):
    def pin(name):
        return {"path": name, "bytes": 1, "sha256": "a" * 64}

    runtime = {"python": "synthetic exact environment"}
    monkeypatch.setattr(workbench.uv, "runtime_fingerprint", lambda: runtime)
    flags = {"research_only": True, **dict.fromkeys(workbench.mask.FALSE_FLAGS, False)}
    roles = {name: pin(f"metadata/{name}.json") for name in workbench.ROLES}
    primary_roles = {
        name: roles["uv_report"] if name == "uv_report" else pin(f"prior/{name}.json")
        for name in workbench.mask.ROLES
    }
    selected, primary_rows, audit_rows = [], [], []
    for source, ages in workbench.uv.COHORT.items():
        label = int(source[-2:])
        for age in ages:
            sample = f"{source}--sam-{age:03d}"
            registration = {
                "sample_id": sample,
                "source_id": source,
                "target_age": age,
                "source_age_label": label,
            }
            selected.append({"registration": registration})
            common = {
                "sample_id": sample,
                "pixel_comparison": {"exact": True},
                "layer_pixel_counts": {"allowed": 16},
                "decomposition": {"synthetic": 16},
            }
            primary_rows.append(
                {
                    **copy.deepcopy(common),
                    "status": "ok",
                    "source_id": source,
                    "target_age_condition": age,
                    "source_age_label": label,
                    "source_age": dict(workbench.uv.UNKNOWN_AGE),
                }
            )
            audit_rows.append(
                {
                    **copy.deepcopy(common),
                    "primary_diagnostics_equal": True,
                    "independent_partition_region_count_check": True,
                }
            )
    primary = {
        "schema_version": 1,
        "protocol_id": workbench.mask.PROTOCOL_ID,
        **flags,
        "inputs": [pin(f"input/{index}.json") for index in range(130)],
        "runtime": runtime,
        "roles": primary_roles,
        "study_plan": pin("prior/study-plan.json"),
        "summary": {
            "requested_targets": 12,
            "all_masks_pixel_equal": True,
            "all_requested_verified": True,
            "decomposition_targets": 12,
        },
        "integrity": {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": 130,
        },
        "records": primary_rows,
    }
    audit = {
        "schema_version": 1,
        "audit_protocol": "independent-mask-replay-audit-v1",
        "status": "passed",
        **flags,
        "primary_report": roles["mask_report"],
        "study_plan": primary["study_plan"],
        "independent_script": pin("prior/independent_audit.py"),
        "runtime": runtime,
        "verified_input_count": 130,
        "imports_project_implementation": False,
        "all_masks_pixel_equal": True,
        "all_primary_diagnostics_equal": True,
        "decomposition_targets": 12,
        "source_age_defaults_introduced": 0,
        "integrity": {
            "all_inputs_unchanged_before_publication": True,
            "plan_report_script_unchanged_before_publication": True,
            "runtime_unchanged_before_publication": True,
        },
        "records": audit_rows,
    }
    metadata = {"mask_report": primary, "mask_audit": audit, "uv_report": {"synthetic": True}}
    old_metadata = {
        name: metadata["uv_report"] if name == "uv_report" else {} for name in workbench.mask.ROLES
    }
    old_plan = copy.deepcopy(
        {
            "schema_version": 1,
            "protocol_id": workbench.mask.PROTOCOL_ID,
            "inputs": primary["inputs"],
            "roles": primary_roles,
            "runtime": runtime,
        }
    )

    class SyntheticInputs:
        prior_plan = old_plan

        def read(self, item, limit):
            del limit
            if item == primary["study_plan"]:
                return json.dumps(self.prior_plan).encode()
            name = next(name for name, value in primary_roles.items() if item == value)
            return json.dumps(old_metadata[name]).encode()

    old_records = {row["registration"]["sample_id"]: {} for row in selected}
    monkeypatch.setattr(workbench.mask, "_protocol", lambda value: None)
    monkeypatch.setattr(workbench.mask, "_selected", lambda *args: (selected, old_records))
    return SyntheticInputs(), roles, metadata, selected, old_records


def test_rle_preserves_row_major_runs_and_singletons_without_mutation():
    source = np.array([[0, 0, 4], [4, 4, 2]], dtype=np.uint8)
    before = source.copy()
    assert workbench.encode_rle(source, max_label=4) == [0, 2, 4, 3, 2, 1]
    np.testing.assert_array_equal(source, before)
    assert workbench.encode_rle(np.array([3], dtype=np.uint8), max_label=4) == [3, 1]


@pytest.mark.parametrize(
    "array", [np.array([-1]), np.array([5]), np.array([np.nan]), np.array([1.5])]
)
def test_rle_rejects_unknown_negative_or_noninteger_labels(array):
    with pytest.raises((TypeError, ValueError)):
        workbench.encode_rle(array, max_label=4)


def test_embedded_json_escapes_every_less_than_without_altering_observational_text():
    text = '</script><img src=x onerror="alert(1)"> & <汉字>\u2028\u2029'
    encoded = workbench.embedded_json({"review": text, "unknown": None})
    assert "<" not in encoded and "</script" not in encoded.lower()
    assert json.loads(encoded) == {"review": text, "unknown": None}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_embedded_json_refuses_nonfinite_numbers(value):
    with pytest.raises(ValueError):
        workbench.embedded_json({"value": value})


def test_vectors_keep_exact_little_endian_c_order_bytes_and_negative_zero():
    arrays = synthetic_vectors()
    encoded = workbench.encode_vectors(arrays)
    names = {
        "rows_columns_i32": "texel_rows_columns",
        "face_owner_i32": "face_owner",
        "barycentric_f64": "barycentric",
        "target_xyz_f64": "target_xyz",
        "source_canonical_xyz_f64": "source_canonical_xyz",
        "region_bits_u8": "region_bits",
        "rejection_partition_u8": "rejection_partition",
    }
    assert encoded["count"] == 2
    assert set(encoded) == {"count", *names}
    for output_name, source_name in names.items():
        assert base64.b64decode(encoded[output_name], validate=True) == arrays[source_name].tobytes(
            order="C"
        )
    target = np.frombuffer(base64.b64decode(encoded["target_xyz_f64"]), dtype="<f8")
    assert target[3] == 2**-40 and np.signbit(target[4])


@pytest.mark.parametrize("problem", ["row_count", "nonfinite", "extra", "missing"])
def test_vectors_fail_closed_on_schema_or_payload_mismatch(problem):
    arrays = synthetic_vectors()
    if problem == "row_count":
        arrays["face_owner"] = arrays["face_owner"][:1]
    elif problem == "nonfinite":
        arrays["target_xyz"][0, 0] = np.nan
    elif problem == "extra":
        arrays["unregistered"] = np.zeros(2, dtype=np.uint8)
    else:
        del arrays["region_bits"]
    with pytest.raises((KeyError, TypeError, ValueError)):
        workbench.encode_vectors(arrays)


def test_case_html_binds_exact_utf8_module_hash_and_keeps_json_inert():
    script = 'export const label = "研究 <text>";\n'
    text = '</script><script>alert("untrusted")</script>'
    data = {"sampleId": "synthetic", "observation": text}
    document = workbench.render_case_document(data, template(), script)
    html = document.decode("utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in html
    modules = re.findall(r'<script type="module">(.*?)</script>', html, flags=re.S)
    assert modules == [script]
    raw_data = re.search(r'<script id="case-data" type="application/json">(.*?)</script>', html)
    assert raw_data and "<" not in raw_data.group(1)
    assert json.loads(raw_data.group(1)) == data
    assert html.lower().count("</script>") == 2
    for directive in (
        "default-src 'none'",
        "connect-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ):
        assert directive in html


@pytest.mark.parametrize(
    "marker", ["__WORKBENCH_DATA__", "__WORKBENCH_SCRIPT__", "__WORKBENCH_SCRIPT_HASH__"]
)
@pytest.mark.parametrize("count", [0, 2])
def test_html_template_requires_each_security_marker_exactly_once(marker, count):
    source = template().replace(marker, marker * count)
    with pytest.raises(ValueError):
        workbench.render_case_document({}, source, "export {};\n")


@pytest.mark.parametrize("script", ["</script>", "</ScRiPt >", "x=1;<!-- open", "export {};\r\n"])
def test_inline_module_cannot_break_out_of_the_script_element(script):
    with pytest.raises(ValueError):
        workbench.render_case_document({}, template(), script)


def test_untrusted_json_marker_text_is_not_reexpanded_as_module_source():
    payload = {"review": "__WORKBENCH_SCRIPT__ __WORKBENCH_SCRIPT_HASH__ __WORKBENCH_DATA__"}
    document = workbench.render_case_document(payload, template(), "export {};\n").decode()
    raw_data = re.search(r'<script id="case-data" type="application/json">(.*?)</script>', document)
    assert raw_data and json.loads(raw_data.group(1)) == payload
    assert document.count('type="module"') == 1


def test_page_and_batch_byte_budgets_fail_before_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PAGE_LIMIT", 8)
    with pytest.raises(ValueError):
        workbench.render_case_document({}, template(), "export {};")
    pages, report = publication_fixture()
    with pytest.raises(ValueError):
        workbench.publish_pages(tmp_path / "per-page", pages, report, lambda: None)
    assert not (tmp_path / "per-page").exists()
    monkeypatch.setattr(workbench, "PAGE_LIMIT", 1024)
    monkeypatch.setattr(workbench, "TOTAL_PAGE_LIMIT", sum(map(len, pages.values())) - 1)
    with pytest.raises(ValueError):
        workbench.publish_pages(tmp_path / "batch", pages, report, lambda: None)
    assert not (tmp_path / "batch").exists()


def test_incomplete_page_cohort_is_not_partially_published(tmp_path):
    pages, report = publication_fixture()
    del pages[next(name for name in pages if name.startswith("cases/"))]
    with pytest.raises(ValueError):
        workbench.publish_pages(tmp_path / "partial", pages, report, lambda: None)
    assert not (tmp_path / "partial").exists()


@pytest.mark.parametrize("problem", ["missing_record", "foreign_case", "empty_success"])
def test_published_pages_must_match_all_twelve_successful_evidence_records(tmp_path, problem):
    pages, report = publication_fixture()
    if problem == "missing_record":
        report["records"].pop()
    elif problem == "foreign_case":
        old_name = next(name for name in pages if name.startswith("cases/"))
        pages["cases/foreign-case.html"] = pages.pop(old_name)
    else:
        pages.clear()
    with pytest.raises(ValueError):
        workbench.publish_pages(tmp_path / "inconsistent", pages, report, lambda: None)
    assert not (tmp_path / "inconsistent").exists()


def test_exact_successful_report_audit_and_whole_cohort_bind_before_asset_decode(monkeypatch):
    inputs, roles, metadata, selected, old_records = evidence_fixture(monkeypatch)
    assert workbench.validate_evidence(inputs, roles, metadata) == (selected, old_records)
    inherited = workbench.derive_input_pins(metadata)
    assert len(inherited) == 132
    assert {value["path"] for value in inherited} == {
        *(value["path"] for value in metadata["mask_report"]["inputs"]),
        "prior/study-plan.json",
        "prior/independent_audit.py",
    }


@pytest.mark.parametrize(
    "problem",
    [
        "missing_target",
        "masks_differ",
        "not_all_verified",
        "incomplete_decomposition",
        "runtime_drift",
        "input_integrity_false",
        "quality_promotion",
        "audit_wrong_report",
        "audit_wrong_plan",
        "audit_incomplete",
        "audit_not_independent",
        "source_age_default",
        "record_target_age",
        "audit_record_missing",
        "audit_record_counts",
        "audit_region_check_false",
        "prior_plan_inputs_changed",
        "prior_plan_runtime_changed",
    ],
)
def test_evidence_gate_rejects_reassignment_or_any_missing_cohort_condition(monkeypatch, problem):
    inputs, roles, metadata, _, _ = evidence_fixture(monkeypatch)
    primary, audit = metadata["mask_report"], metadata["mask_audit"]
    if problem == "missing_target":
        primary["summary"]["requested_targets"] = 11
    elif problem == "masks_differ":
        primary["summary"]["all_masks_pixel_equal"] = False
    elif problem == "not_all_verified":
        primary["summary"]["all_requested_verified"] = False
    elif problem == "incomplete_decomposition":
        primary["summary"]["decomposition_targets"] = 11
    elif problem == "runtime_drift":
        primary["runtime"] = {"python": "changed"}
    elif problem == "input_integrity_false":
        primary["integrity"]["all_inputs_unchanged"] = False
    elif problem == "quality_promotion":
        primary["age_quality_accepted"] = True
    elif problem == "audit_wrong_report":
        audit["primary_report"] = {**roles["mask_report"], "sha256": "b" * 64}
    elif problem == "audit_wrong_plan":
        audit["study_plan"] = {**primary["study_plan"], "sha256": "b" * 64}
    elif problem == "audit_incomplete":
        audit["decomposition_targets"] = 11
    elif problem == "audit_not_independent":
        audit["imports_project_implementation"] = True
    elif problem == "source_age_default":
        primary["records"][0]["source_age"] = {"value": 30, "method": "default"}
    elif problem == "record_target_age":
        primary["records"][0]["target_age_condition"] = 21
    elif problem == "audit_record_missing":
        audit["records"].pop()
    elif problem == "audit_record_counts":
        audit["records"][0]["decomposition"]["synthetic"] += 1
    elif problem == "audit_region_check_false":
        audit["records"][0]["independent_partition_region_count_check"] = False
    elif problem == "prior_plan_inputs_changed":
        inputs.prior_plan["inputs"].pop()
    else:
        inputs.prior_plan["runtime"] = {"python": "changed"}
    with pytest.raises(ValueError):
        workbench.validate_evidence(inputs, roles, metadata)


def test_conflicting_inherited_evidence_pin_is_rejected_instead_of_last_write_wins(monkeypatch):
    _, _, metadata, _, _ = evidence_fixture(monkeypatch)
    original = metadata["mask_report"]["inputs"][0]
    metadata["mask_report"]["inputs"].append({**original, "sha256": "b" * 64})
    with pytest.raises(ValueError):
        workbench.derive_input_pins(metadata)


def test_publication_refuses_existing_directory_without_touching_sentinel(tmp_path):
    output = tmp_path / "already-exists"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_bytes(b"keep")
    pages, report = publication_fixture()
    with pytest.raises((FileExistsError, ValueError)):
        workbench.publish_pages(output, pages, report, lambda: None)
    assert sentinel.read_bytes() == b"keep" and sorted(p.name for p in output.iterdir()) == [
        "sentinel.txt"
    ]


@pytest.mark.parametrize(
    "name", ["../escape.html", "/absolute.html", "cases/../../escape.html", "cases\\bad.html"]
)
def test_publication_rejects_page_paths_outside_the_new_output(tmp_path, name):
    pages, report = publication_fixture()
    pages[name] = b"bad"
    with pytest.raises((TypeError, ValueError)):
        workbench.publish_pages(tmp_path / "new", pages, report, lambda: None)
    assert not (tmp_path / "escape.html").exists()


@pytest.mark.parametrize("fail_on", [1, 2, 3])
def test_every_integrity_failure_invalidates_all_twelve_and_removes_only_owned_pages(
    tmp_path, fail_on
):
    pages, report = publication_fixture()
    original = copy.deepcopy(report)
    output = tmp_path / f"drift-{fail_on}"
    calls = 0

    def audit():
        nonlocal calls
        calls += 1
        if calls == fail_on:
            if output.exists():
                (output / "foreign-note.txt").write_bytes(b"do not remove")
            raise ValueError("synthetic late input/source/runtime drift")

    result = workbench.publish_pages(output, pages, report, audit)
    assert len(result["records"]) == 12
    assert all(row["status"] == "invalidated_input_drift" for row in result["records"])
    assert all(
        row["error_code"] == "INPUT_DRIFT" and row["artifacts"] == {} for row in result["records"]
    )
    assert result["summary"]["all_requested_verified"] is False
    assert result["summary"]["artifact_pages"] == 0
    assert result["summary"]["invalidated"] == 12
    assert not list(output.rglob("*.html"))
    if fail_on > 1:
        assert (output / "foreign-note.txt").read_bytes() == b"do not remove"
    saved = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert saved == result
    assert original["records"][0]["status"] == "ok"


def test_successful_publication_checks_each_page_hash_and_all_three_integrity_phases(tmp_path):
    pages, report = publication_fixture()
    output = tmp_path / "published"
    calls = []

    def audit():
        calls.append(output.exists())

    result = workbench.publish_pages(output, pages, report, audit)
    assert calls == [False, True, True]
    assert result["summary"]["all_requested_verified"] is True
    for name, data in pages.items():
        assert (output / name).read_bytes() == data
    assert json.loads((output / "report.json").read_text()) == result
