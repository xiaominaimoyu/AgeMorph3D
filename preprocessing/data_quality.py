"""P06 declaration/saved-feature coverage reports; no quality acceptance or training.

python -m preprocessing.data_quality --help
Reads bounded metadata only. Missing measurements stay null, not zero.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from . import dataset_manifest as metadata
from . import feature_join as joiner
from . import resource_acquisition as acquisition

SCHEMA = "agemorph3d-data-quality-report-v1"
MAX_JSON = joiner.MAX_JSON
MAX_PLAN = joiner.MAX_PLAN
MAX_RECORDS = 5000
Error, require, safe = joiner.Error, joiner.require, joiner.safe
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = {
    **joiner._SOURCES,
    "preprocessing/data_quality.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
PRODUCER_SHA256 = _SOURCES["preprocessing/data_quality.py"]
FLAGS = {
    **joiner.FLAGS,
    "human_quality_review_verified": False,
    "binary_integrity_verified": False,
    "near_duplicates_recomputed": False,
    "no_leakage_accepted": False,
}


def _load_join(inputs, pin, manifest, manifest_pin):
    value = inputs.load(pin)
    require(
        type(value) is dict
        and value.get("schema_id") == joiner.SCHEMA
        and value.get("producer_sha256") == joiner.PRODUCER_SHA256
        and joiner.freeze._same(value.get("dependency_sha256"), joiner._SOURCES)
        and value.get("inputs_stable") is True
        and value.get("changed_inputs") == []
        and value.get("research_only") is True
        and value.get("provenance_assessment")
        == "saved_metadata_and_self_reported_declarations_only"
        and all(value.get(k) is False for k in joiner.FLAGS),
        "P05_VERSION_BOUNDARY_OR_STABILITY_MISMATCH",
    )
    pins = value.get("inputs")
    require(type(pins) is list and bool(pins), "P05_INPUTS_MISSING")
    replay = joiner.freeze._Inputs(inputs.root)
    plan = acquisition._json(replay.read(pins[0], maximum=joiner.MAX_PLAN))
    acquisition._keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "precheck_report",
            "frozen_inputs",
            "feature_report",
            "expected_binding",
            "mappings",
            "reserve_bytes",
        ),
    )
    require(
        plan["schema_id"] == joiner.SCHEMA
        and acquisition._identifier(plan["plan_id"])
        and plan["plan_id"] == value.get("plan_id")
        and pins[0]["sha256"] == value.get("plan_sha256")
        and acquisition._integer(plan["reserve_bytes"], 0, 64 * 1024**3),
        "P05_PLAN_BINDING_MISMATCH",
    )
    packet = joiner.load_frozen(replay, plan["precheck_report"], plan["frozen_inputs"])
    require(
        packet["manifest"] == manifest
        and sum(p == manifest_pin for p in packet["input_pins"]) == 1,
        "P05_COHORT_MISMATCH",
    )
    dataset = joiner.load_k1(replay, plan["feature_report"])
    require(
        joiner.freeze._same(dataset["binding"], plan["expected_binding"]),
        "P05_FEATURE_BINDING_MISMATCH",
    )
    rows, features, selected = joiner._join_rows(packet, dataset, plan["mappings"])
    expected_summary = {
        "requested": len(rows),
        "joined": len(features["shape"]),
        "failed": len(rows) - len(features["shape"]),
        "feature_rows_before_final_check": len(features["shape"]),
        "failure_codes": dict(Counter(r["error_code"] for r in rows if r["status"] == "failed")),
        "uses": dict(Counter(r["k5"]["use"] for r in rows)),
    }
    unmapped = [
        {"sample_id": r["sample_id"], "fit_status": r["fit_status"], "error_code": r["error_code"]}
        for r in dataset["records"]
        if r["sample_id"] not in selected
    ]
    require(
        value.get("status") == ("passed" if len(features["shape"]) == len(rows) else "failed")
        and joiner.freeze._same(value.get("records"), rows)
        and joiner.freeze._same(value.get("features"), features)
        and joiner.freeze._same(value.get("summary"), expected_summary)
        and joiner.freeze._same(value.get("binding"), dataset["binding"])
        and joiner.freeze._same(value.get("source_summary"), dataset["summary"])
        and joiner.freeze._same(
            value.get("source_dataset_provenance"), dataset["dataset_provenance"]
        )
        and value.get("unmapped_source_records") == unmapped
        and joiner.freeze._same(value.get("metadata_audit"), metadata.audit_manifest(manifest))
        and list(replay.pins.values()) == pins,
        "P05_SAVED_REPORT_REPLAY_MISMATCH",
    )
    for source_pin in replay.pins.values():
        inputs.read(source_pin, suffixes=(".json", ".md", ".py"))
    return value


def _ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def summarize(manifest, feature_report=None):
    """Descriptive counts only; no train-fitted parameters or quality exclusion."""
    manifest = metadata.validate_manifest(manifest)
    rows = manifest["records"]
    require(len(rows) <= MAX_RECORDS, "RECORD_COUNT_LIMIT")
    audit = metadata.audit_manifest(manifest)
    if feature_report is not None:
        require([r["k5"] for r in feature_report["records"]] == rows, "SUMMARY_COHORT_MISMATCH")
    bins = audit["summary"]["exact_age_bins_20_70"]
    exact = [r["age"]["value"] for r in rows if r["age"]["kind"] == "exact"]
    age_scope = {
        kind: dict(
            Counter(
                c["age_scope"]
                for r, c in zip(rows, audit["record_checks"], strict=True)
                if r["age"]["kind"] == kind
            )
        )
        for kind in ("exact", "interval", "unknown")
    }
    historical = {
        s: sum(r["processing"]["status"] == s for r in rows)
        for s in ("not_checked", "ok", "failed", "excluded")
    }
    by_use = {}
    for use in metadata.USES:
        selected = [r for r in rows if r["use"] == use]
        by_use[use] = {
            "records": len(selected),
            "local_subjects_declared": len(
                {
                    (r["dataset_id"], r["subject_id"])
                    for r in selected
                    if r["subject_id"] is not None
                }
            ),
            "age_kinds": {
                k: sum(r["age"]["kind"] == k for r in selected)
                for k in ("exact", "interval", "unknown")
            },
        }
    features = None
    if feature_report is not None:
        joined = sum(r["status"] == "joined" for r in feature_report["records"])
        features = {
            "requested": len(rows),
            "joined": joined,
            "failed": len(rows) - joined,
            "join_coverage": _ratio(joined, len(rows)),
            "join_failure_codes": dict(
                Counter(
                    r["error_code"] for r in feature_report["records"] if r["status"] == "failed"
                )
            ),
            "mapped_source_error_codes": dict(
                Counter(
                    r["source_error_code"]
                    for r in feature_report["records"]
                    if r["source_error_code"] is not None
                )
            ),
            "source_summary": copy.deepcopy(feature_report["source_summary"]),
            "unmapped_source_records": copy.deepcopy(feature_report["unmapped_source_records"]),
            "meaning": (
                "Saved engineering coverage; not reconstruction accuracy or quality exclusion rate"
            ),
        }
    statistics = {
        "records": len(rows),
        "datasets": len(manifest["datasets"]),
        "by_use": by_use,
        "formal_split_records": audit["summary"]["formal_split_records"],
        "identity_declarations": {
            "local_subjects": audit["summary"]["local_subjects"],
            "explicit_linked_subject_ids": len(
                {r["linked_subject_id"] for r in rows if r["linked_subject_id"] is not None}
            ),
            "unknown_subject_records": audit["summary"]["unknown_subject_records"],
        },
        "age": {
            "kinds": {
                k: sum(r["age"]["kind"] == k for r in rows)
                for k in ("exact", "interval", "unknown")
            },
            "scope_by_kind": age_scope,
            "exact_label_min": min(exact) if exact else None,
            "exact_label_max": max(exact) if exact else None,
            "exact_bins_20_70": {
                k: bins.get(k, 0) for k in ("20-29", "30-39", "40-49", "50-59", "60-69", "70")
            },
        },
        "historical_processing": historical,
        "historical_failure_reasons": dict(
            Counter(
                r["processing"]["reason"] for r in rows if r["processing"]["status"] == "failed"
            )
        ),
        "declared_exclusion_ratio": _ratio(historical["excluded"], len(rows)),
        "exposure_declarations": {
            field: {
                v: sum(r["exposure"][field] == v for r in rows) for v in ("yes", "no", "unknown")
            }
            for field in ("preprocessing", "model_selection", "result_inspection")
        },
        "dataset_registrations": [
            {
                "dataset_id": d["dataset_id"],
                "version": d["version"],
                **{
                    f: d[f]["status"]
                    for f in (
                        "purpose_registration",
                        "identity_review",
                        "near_duplicate_review",
                        "training_overlap",
                    )
                },
                "evidence_integrity_rechecked": False,
            }
            for d in manifest["datasets"]
        ],
        "finding_counts": dict(Counter(f["code"] for f in audit["findings"])),
        "saved_features": features,
        "unmeasured": {
            k: None
            for k in (
                "actual_quality_exclusion_rate",
                "raw_image_bytes",
                "archive_bytes",
                "derived_geometry_bytes",
                "inference_seconds",
                "images_per_second",
                "gpu_peak_bytes",
                "formal_training_budget_hours",
            )
        },
    }
    ledger = [
        {
            "k5": copy.deepcopy(r),
            "age_scope": c["age_scope"],
            "join_status": None
            if feature_report is None
            else feature_report["records"][i]["status"],
            "join_error_code": None
            if feature_report is None
            else feature_report["records"][i]["error_code"],
            "source_error_code": None
            if feature_report is None
            else feature_report["records"][i]["source_error_code"],
        }
        for i, (r, c) in enumerate(zip(rows, audit["record_checks"], strict=True))
    ]
    return {"statistics": statistics, "records": ledger, "metadata_audit": audit}


def _cell(value):
    text = "未测/未核" if value is None else str(value)
    for old, new in (
        ("\\", "\\\\"),
        ("|", "\\|"),
        ("`", "\\`"),
        ("[", "\\["),
        ("]", "\\]"),
        ("<", "&lt;"),
        (">", "&gt;"),
        ("\r", " "),
        ("\n", " "),
    ):
        text = text.replace(old, new)
    return text


def render_markdown(report):
    lines = [
        "# 数据预处理质检：声明与保存工程观察",
        "",
        f"状态：{report['status']}；输入模式：{report['input_mode']}。",
        "",
        "未核验当前图片/二进制、真实身份、许可正文或人工质量；统计不授予训练、独立评价或生产资格。",
        "",
    ]
    s = report["statistics"]
    if s is None:
        lines += ["输入或源码在末检变化，统计结果未发布。完整历史快照行保留在JSON中。", ""]
    else:
        lines += [
            f"声明记录：{s['records']}；数据集：{s['datasets']}；局部subject声明：{s['identity_declarations']['local_subjects']}。",
            "",
            "| 用途 | 记录 | 局部subject声明 | exact | interval | unknown |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for use, row in s["by_use"].items():
            lines.append(
                f"| {_cell(use)} | {row['records']} | {row['local_subjects_declared']} | "
                f"{row['age_kinds']['exact']} | {row['age_kinds']['interval']} | "
                f"{row['age_kinds']['unknown']} |"
            )
        lines += [
            "",
            "| 精确标签范围 | 最小 | 最大 |",
            "|---|---:|---:|",
            f"| 保存声明，非独立年龄真值 | {_cell(s['age']['exact_label_min'])} | "
            f"{_cell(s['age']['exact_label_max'])} |",
            "",
            "| 精确标签年龄箱 | 数量 |",
            "|---|---:|",
        ]
        lines += [f"| {key} | {value} |" for key, value in s["age"]["exact_bins_20_70"].items()]
        lines += [
            "",
            "区间不取中点、不进入精确年龄箱；未知值保持null。范围外/跨界记录详见JSON。",
            "",
            "| 历史processing声明 | 数量 |",
            "|---|---:|",
        ]
        lines += [f"| {key} | {value} |" for key, value in s["historical_processing"].items()]
        lines += ["", "| 曝光声明 | yes | no | unknown |", "|---|---:|---:|---:|"]
        lines += [
            f"| {key} | {value['yes']} | {value['no']} | {value['unknown']} |"
            for key, value in s["exposure_declarations"].items()
        ]
        lines += [
            "",
            "| 数据集 | 版本 | 用途 | 身份 | 近重复 | 训练重叠 |",
            "|---|---|---|---|---|---|",
        ]
        for d in s["dataset_registrations"]:
            lines.append(
                "| "
                + " | ".join(
                    _cell(d[k])
                    for k in (
                        "dataset_id",
                        "version",
                        "purpose_registration",
                        "identity_review",
                        "near_duplicate_review",
                        "training_overlap",
                    )
                )
                + " |"
            )
        lines += ["", "| 声明审计待办 | 数量 |", "|---|---:|"]
        lines += [f"| {_cell(key)} | {value} |" for key, value in s["finding_counts"].items()]
        feature = s["saved_features"]
        if feature is None:
            lines += ["", "保存特征观察：未提供，不能把未读取解释为0个成功或0个失败。", ""]
        else:
            lines += [
                "",
                f"保存特征对接：{feature['joined']}/{feature['requested']}；失败{feature['failed']}。仅为工程覆盖，不是重建精度或质量排除率。",
                f"K1完整源分母：{feature['source_summary']['requested']}，成功{feature['source_summary']['valid']}，失败{feature['source_summary']['failed']}；未映射源请求{len(feature['unmapped_source_records'])}。",
                "",
                "| 对接失败码 | 数量 |",
                "|---|---:|",
            ]
            lines += [
                f"| {_cell(key)} | {value} |"
                for key, value in feature["join_failure_codes"].items()
            ]
        lines += ["", "| 未测项目 | 值 |", "|---|---|"]
        lines += [f"| {key} | {_cell(value)} |" for key, value in s["unmeasured"].items()]
    lines += ["", "| 已读元信息 | 字节 | SHA-256 |", "|---|---:|---|"]
    lines += [f"| {_cell(p['path'])} | {p['bytes']} | {p['sha256']} |" for p in report["inputs"]]
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_report(root, plan_name, plan_sha256, output):
    root = Path(root).absolute()
    require(
        root.is_dir() and root == root.resolve() and acquisition._sha(plan_sha256),
        "INVALID_ROOT_OR_PLAN_PIN",
    )
    body = acquisition._read(safe(root, plan_name), MAX_PLAN)
    require(hashlib.sha256(body).hexdigest() == plan_sha256, "PLAN_SHA256_MISMATCH")
    inputs = joiner.freeze._Inputs(root)
    inputs.read({"path": plan_name, "bytes": len(body), "sha256": plan_sha256}, maximum=MAX_PLAN)
    plan = acquisition._json(body)
    acquisition._keys(
        plan, ("schema_id", "plan_id", "manifest", "feature_join_report", "reserve_bytes")
    )
    require(
        plan["schema_id"] == SCHEMA and acquisition._identifier(plan["plan_id"]), "INVALID_PLAN"
    )
    require(acquisition._integer(plan["reserve_bytes"], 0, 64 * 1024**3), "INVALID_RESERVE")
    manifest = metadata.validate_manifest(inputs.load(plan["manifest"]))
    require(len(manifest["records"]) <= MAX_RECORDS, "RECORD_COUNT_LIMIT")
    feature_report = (
        None
        if plan["feature_join_report"] is None
        else _load_join(inputs, plan["feature_join_report"], manifest, plan["manifest"])
    )
    calculated = summarize(manifest, feature_report)
    changed = inputs.changed()
    for name, digest in _SOURCES.items():
        try:
            require(
                hashlib.sha256((_ROOT / name).read_bytes()).hexdigest() == digest, "SOURCE_CHANGED"
            )
        except (Error, OSError):
            changed.append(name)
    report = {
        "schema_id": SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_sha256,
        "producer_sha256": PRODUCER_SHA256,
        "dependency_sha256": _SOURCES,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "inputs": list(inputs.pins.values()),
        "inputs_stable": not changed,
        "changed_inputs": sorted(set(changed)),
        "input_mode": "manifest_only" if feature_report is None else "saved_feature_join",
        "research_only": True,
        "status": "invalidated" if changed else "reported",
        "provenance_assessment": "declarations_and_saved_engineering_observations_only",
        "manifest_id": manifest["manifest_id"],
        "snapshot_record_count": len(manifest["records"]),
        **calculated,
        "metadata_bytes_verified": inputs.total,
        "metadata_files_verified": len(inputs.pins),
        **FLAGS,
    }
    if changed:
        report.update(statistics=None, metadata_audit=None)
    markdown = render_markdown(report)
    payload = acquisition._encoded(report)
    require(len(payload) <= MAX_JSON and len(markdown) <= MAX_JSON, "REPORT_TOO_LARGE")
    target = safe(root, output)
    require(output.startswith("output/research/") and not target.exists(), "OUTPUT_MUST_BE_NEW")
    require(
        shutil.disk_usage(root).free >= plan["reserve_bytes"] + 2 * MAX_JSON, "INSUFFICIENT_SPACE"
    )
    target.mkdir(parents=True, exist_ok=False)
    for name, content in (("report.json", payload), ("report.md", markdown)):
        with safe(root, output + "/" + name).open("xb") as stream:
            stream.write(content)
    return {**report, "receipt": output + "/report.json", "markdown": output + "/report.md"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = export_report(args.root, args.plan, args.plan_sha256, args.output_dir)
    except (Error, OSError, ValueError, KeyError, TypeError, OverflowError, IndexError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **FLAGS}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "reported" else 1


if __name__ == "__main__":
    sys.exit(main())
