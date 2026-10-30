"""T01 bounded metadata preflight; records declarations without authorizing training.

python -m training.preflight --help
Never reads images, weights, saved scores or fits parameters.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from preprocessing import data_quality as quality

SCHEMA = "agemorph3d-training-preflight-v1"
DRAFT_SCHEMA = "agemorph3d-baseline-draft-v1"
REVIEW_SCHEMA = "agemorph3d-training-entry-review-v1"
GATES = (
    "model_purpose",
    "data_purpose",
    "R11",
    "R12",
    "R13",
    "R14",
    "P04_human_freeze",
    "E01_execution_protocol",
    "P06_quality_budget",
)
POLICY = {
    "selection_use": "validation_only",
    "test_scores_read": False,
    "automatic_selection": False,
    "statistics_fit_use": "qualified_train_only",
    "unknown_age": "retain_null_no_imputation",
    "failed_samples": "retain_full_denominator_no_zero_fill",
}
FLAGS = {
    **quality.FLAGS,
    "training_run": False,
    "test_scores_read": False,
    "automatic_selection": False,
    "review_authenticity_verified": False,
}
Error, require, safe = quality.Error, quality.require, quality.safe
acquisition, joiner, metadata = quality.acquisition, quality.joiner, quality.metadata
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = {
    **quality._SOURCES,
    **{
        name: hashlib.sha256((_ROOT / name).read_bytes()).hexdigest()
        for name in ("training/preflight.py", "training/__init__.py")
    },
}
PRODUCER_SHA256 = _SOURCES["training/preflight.py"]


def validate_draft(value):
    acquisition._keys(
        value,
        (
            "schema_id",
            "draft_id",
            "status",
            "purpose",
            "seed",
            "models",
            "candidates",
            "environment",
            "protocol",
            "policy",
            "short_run",
            "measured_budget",
        ),
    )
    require(
        value["schema_id"] == DRAFT_SCHEMA
        and acquisition._identifier(value["draft_id"])
        and value["status"] == "draft_not_executable"
        and value["purpose"] == "local_noncommercial_research_demonstration"
        and acquisition._integer(value["seed"], 0, 2**32 - 1),
        "INVALID_DRAFT",
    )
    require(joiner.freeze._same(value["policy"], POLICY), "INVALID_SELECTION_POLICY")
    models = value["models"]
    require(type(models) is list and len(models) == 2, "MODEL_ROLES_REQUIRED")
    for model in models:
        acquisition._keys(model, ("role", "manifest", "model_id", "revision"))
        require(
            model["role"] in ("detector", "reconstructor")
            and metadata._identifier(model["model_id"])
            and type(model["revision"]) is str
            and 0 < len(model["revision"]) <= 512,
            "INVALID_MODEL_BINDING",
        )
    require(
        [m["role"] for m in models] == ["detector", "reconstructor"],
        "MODEL_ROLES_REQUIRED",
    )
    candidates = value["candidates"]
    expected = (
        "detector_pretrained",
        "reconstruction_pretrained",
        "age_no_change",
        "age_ridge",
    )
    require(type(candidates) is list and len(candidates) == 4, "CANDIDATES_REQUIRED")
    for candidate, name in zip(candidates, expected, strict=True):
        acquisition._keys(candidate, ("id", "version", "config"))
        require(
            candidate["id"] == name and candidate["version"] == 1, "INVALID_CANDIDATE"
        )
    detector, recon, static, ridge = [c["config"] for c in candidates]
    acquisition._keys(detector, ("input_size", "confidence", "iou"))
    require(
        acquisition._integer(detector["input_size"], 32, 2048)
        and detector["input_size"] % 32 == 0,
        "INVALID_DETECTION_CONFIG",
    )
    for key in ("confidence", "iou"):
        require(
            type(detector[key]) in (int, float) and 0 < detector[key] <= 1,
            "INVALID_DETECTION_CONFIG",
        )
    require(
        recon
        == {"input_size": 120, "shape_dimensions": 40, "expression_dimensions": 10}
        and static == {"immutable_source_anchor": True, "age_range": [20, 70]}
        and ridge
        == {
            "relative_ridge_grid": [0.0, 0.1, 1.0, 10.0],
            "identity_weighting": "equal_identity",
            "standardization": "none",
            "feature_space": "same_basis_shape40",
        },
        "INVALID_GEOMETRY_CONFIG",
    )
    env = value["environment"]
    acquisition._keys(env, ("python_spec", "dependency_files"))
    require(
        env["python_spec"] == ">=3.11,<3.12"
        and type(env["dependency_files"]) is list
        and len(env["dependency_files"]) == 2,
        "INVALID_ENVIRONMENT",
    )
    require(
        [p["path"] for p in env["dependency_files"]]
        == ["backend/pyproject.toml", "backend/uv.lock"],
        "INVALID_DEPENDENCY_PINS",
    )
    acquisition._keys(value["short_run"], ("steps", "batch_size", "device"))
    for key in ("steps", "batch_size"):
        require(
            value["short_run"][key] is None
            or acquisition._integer(value["short_run"][key], 1, 10000),
            "INVALID_SHORT_RUN",
        )
    require(value["short_run"]["device"] in (None, "cpu", "cuda"), "INVALID_SHORT_RUN")
    require(
        value["measured_budget"]
        == {"hours": None, "peak_gpu_bytes": None, "storage_bytes": None},
        "MEASUREMENTS_NOT_SUPPORTED",
    )
    return copy.deepcopy(value)


def _reviews(inputs, pins, scope):
    require(type(pins) is list and len(pins) <= len(GATES), "REVIEW_COUNT_LIMIT")
    result = {}
    for pin in pins:
        value = inputs.load(pin)
        acquisition._keys(
            value,
            (
                "schema_id",
                "gate_id",
                "state",
                "origin",
                "reviewer",
                "scope",
                "evidence",
            ),
        )
        gate = value["gate_id"]
        require(
            type(gate) is str and gate in GATES and gate not in result,
            "INVALID_OR_DUPLICATE_REVIEW_GATE",
        )
        require(
            value["schema_id"] == REVIEW_SCHEMA
            and value["state"] in ("recorded", "pending")
            and value["origin"] in joiner.freeze.ORIGINS
            and (value["reviewer"] is None or metadata._identifier(value["reviewer"])),
            "INVALID_REVIEW",
        )
        require(joiner.freeze._same(value["scope"], scope), "REVIEW_SCOPE_MISMATCH")
        if value["evidence"] is not None:
            inputs.read(value["evidence"], suffixes=(".json", ".md"))
        recorded = (
            value["state"] == "recorded"
            and value["origin"] in ("human", "official")
            and value["reviewer"] is not None
            and value["evidence"] is not None
        )
        result[gate] = {
            "status": "recorded_declaration" if recorded else "blocked",
            "pin": pin,
            "declaration": value,
        }
    return [
        {
            "gate_id": gate,
            **result.get(gate, {"status": "blocked", "pin": None, "declaration": None}),
        }
        for gate in GATES
    ]


def assess(inputs, plan):
    draft = validate_draft(inputs.load(plan["draft"]))
    manifest = metadata.validate_manifest(inputs.load(plan["manifest"]))
    require(len(manifest["records"]) <= quality.MAX_RECORDS, "RECORD_COUNT_LIMIT")
    protocol = inputs.load(draft["protocol"])
    require(
        type(protocol) is dict
        and protocol.get("schema_version") == 1
        and protocol.get("protocol_id") == "agemorph3d-experiment-protocol-v1"
        and all(
            protocol.get(k) is False
            for k in (
                "production_enabled",
                "independent_evaluation",
                "quality_accepted",
                "g3_complete",
            )
        ),
        "INVALID_E01_PROTOCOL",
    )
    for pin in draft["environment"]["dependency_files"]:
        inputs.read(pin, suffixes=(".toml", ".lock"))
    blockers, models = [], []

    def block(code, item):
        blockers.append({"code": code, "item": item})

    for model in draft["models"]:
        saved = inputs.load(model["manifest"])
        require(
            type(saved) is dict
            and saved.get("schema_version") == 1
            and saved.get("model_id") == model["model_id"]
            and saved.get("revision") == model["revision"]
            and saved.get("license_status") in ("verified", "unresolved"),
            "MODEL_BINDING_MISMATCH",
        )
        models.append(
            {
                **model,
                "license_status_declared": saved["license_status"],
                "binary_integrity_verified": False,
            }
        )
        if saved["license_status"] != "verified":
            block("MODEL_PURPOSE_UNRESOLVED", model["role"])
    frozen = plan["freeze"]
    if frozen is None:
        block("P04_INPUTS_MISSING", "freeze")
    else:
        acquisition._keys(frozen, ("report", "packet"))
        packet = joiner.load_frozen(inputs, frozen["report"], frozen["packet"])
        require(
            packet["manifest"] == manifest
            and sum(p == plan["manifest"] for p in packet["input_pins"]) == 1,
            "FROZEN_COHORT_MISMATCH",
        )
        basis = packet["basis"]
        if any(g["origin"] not in ("human", "official") for g in basis["groups"]):
            block("P04_NONHUMAN_GROUP_BASIS", "freeze")
        if any(
            r["origin"] not in ("human", "official") for r in basis["candidate_reviews"]
        ):
            block("P04_NONHUMAN_CANDIDATE_REVIEW", "freeze")
    feature = None
    if plan["feature_join_report"] is None:
        block("P05_SAVED_FEATURES_MISSING", "features")
    else:
        feature = quality._load_join(
            inputs, plan["feature_join_report"], manifest, plan["manifest"]
        )
        feature_plan = inputs.load(feature["inputs"][0])
        require(
            frozen is not None
            and feature_plan["precheck_report"] == frozen["report"]
            and feature_plan["frozen_inputs"] == frozen["packet"],
            "P04_P05_FREEZE_BINDING_MISMATCH",
        )
        if feature["summary"]["failed"]:
            block("P05_SAVED_FEATURE_FAILURES", "features")
    calculated = quality.summarize(manifest, feature)
    for use, count in calculated["statistics"]["formal_split_records"].items():
        if count == 0:
            block("FORMAL_SPLIT_EMPTY", use)
    for finding in calculated["metadata_audit"]["findings"]:
        block("K5_" + finding["code"], finding.get("dataset_id", "manifest"))
    if protocol.get("status") != "reviewed_execution_protocol":
        block("E01_EXECUTION_REVIEW_PENDING", "protocol")
    if any(v is None for v in draft["short_run"].values()):
        block("SHORT_RUN_CONFIG_PENDING", "short_run")
    reviews = _reviews(
        inputs,
        plan["reviews"],
        {
            "draft": plan["draft"],
            "manifest": plan["manifest"],
            "protocol": draft["protocol"],
            "freeze": plan["freeze"],
            "feature_join_report": plan["feature_join_report"],
        },
    )
    for review in reviews:
        if review["status"] == "blocked":
            block("ENTRY_REVIEW_MISSING_OR_PENDING", review["gate_id"])
    return {
        "draft": draft,
        "models": models,
        "entry_reviews": reviews,
        "blockers": blockers,
        **calculated,
    }


def render_markdown(report):
    cell = quality._cell
    lines = [
        "# T01 基线草案与只读训练入口预检",
        "",
        f"状态：{report['status']}。training_authorized=false。",
        "",
        "仅核元信息与自述材料；不验证真实人工身份/许可，不读取测试分数，不启动训练。",
        "R13/R14要求可行性结论与欠项记录，不要求年龄效果或G3提前成功。",
        "",
        "| 缺项代码 | 对象 |",
        "|---|---|",
    ]
    lines += [f"| {cell(r['code'])} | {cell(r['item'])} |" for r in report["blockers"]]
    lines += ["", "| 入口 | 材料声明状态 |", "|---|---|"]
    lines += [f"| {r['gate_id']} | {r['status']} |" for r in report["entry_reviews"]]
    if report["statistics"] is None:
        lines += ["", "末检变化：撤下统计，保留全记录快照和原缺项。"]
    else:
        s = report["statistics"]
        lines += [
            "",
            f"记录{s['records']}；正式组：{cell(s['formal_split_records'])}。",
            "保存处理状态、失败、未知年龄与原用途见JSON全账本；未测预算保持null。",
        ]
    lines += ["", "| 输入元信息 | 字节 | SHA-256 |", "|---|---:|---|"]
    lines += [
        f"| {cell(p['path'])} | {p['bytes']} | {p['sha256']} |"
        for p in report["inputs"]
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def precheck(root, plan_name, plan_sha256, output):
    root = Path(root).absolute()
    require(
        root.is_dir() and root == root.resolve() and acquisition._sha(plan_sha256),
        "INVALID_ROOT_OR_PLAN_PIN",
    )
    body = acquisition._read(safe(root, plan_name), quality.MAX_PLAN)
    require(hashlib.sha256(body).hexdigest() == plan_sha256, "PLAN_SHA256_MISMATCH")
    inputs = joiner.freeze._Inputs(root)
    inputs.read(
        {"path": plan_name, "bytes": len(body), "sha256": plan_sha256},
        maximum=quality.MAX_PLAN,
    )
    plan = acquisition._json(body)
    acquisition._keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "draft",
            "manifest",
            "freeze",
            "feature_join_report",
            "reviews",
            "reserve_bytes",
        ),
    )
    require(
        plan["schema_id"] == SCHEMA and acquisition._identifier(plan["plan_id"]),
        "INVALID_PLAN",
    )
    require(
        acquisition._integer(plan["reserve_bytes"], 0, 64 * 1024**3), "INVALID_RESERVE"
    )
    calculated = assess(inputs, plan)
    changed = inputs.changed()
    for name, digest in _SOURCES.items():
        try:
            require(
                hashlib.sha256((_ROOT / name).read_bytes()).hexdigest() == digest,
                "SOURCE_CHANGED",
            )
        except (Error, OSError):
            changed.append(name)
    if changed:
        calculated.update(statistics=None, metadata_audit=None)
        calculated["blockers"].append(
            {"code": "INPUT_OR_SOURCE_CHANGED", "item": "final_check"}
        )
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
        "status": "invalidated"
        if changed
        else ("blocked" if calculated["blockers"] else "declarations_consistent"),
        "research_only": True,
        "provenance_assessment": "self_reported_metadata_only",
        "execution": "not_implemented_no_authorization",
        "runtime_python": sys.version.split()[0],
        "metadata_bytes_verified": inputs.total,
        "metadata_files_verified": len(inputs.pins),
        **calculated,
        **FLAGS,
    }
    payload, markdown = acquisition._encoded(report), render_markdown(report)
    require(
        len(payload) <= quality.MAX_JSON and len(markdown) <= quality.MAX_JSON,
        "REPORT_TOO_LARGE",
    )
    target = safe(root, output)
    require(
        output.startswith("output/research/") and not target.exists(),
        "OUTPUT_MUST_BE_NEW",
    )
    require(
        shutil.disk_usage(root).free >= plan["reserve_bytes"] + 2 * quality.MAX_JSON,
        "INSUFFICIENT_SPACE",
    )
    target.mkdir(parents=True, exist_ok=False)
    for name, content in (("report.json", payload), ("report.md", markdown)):
        with safe(root, output + "/" + name).open("xb") as stream:
            stream.write(content)
    return {
        **report,
        "receipt": output + "/report.json",
        "markdown": output + "/report.md",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = precheck(args.root, args.plan, args.plan_sha256, args.output_dir)
    except (
        Error,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
        IndexError,
    ) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **FLAGS}))
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "blockers": report["blockers"],
                "receipt": report["receipt"],
                **FLAGS,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "declarations_consistent" else 1


if __name__ == "__main__":
    sys.exit(main())
