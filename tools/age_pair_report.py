"""Compare exact-age real/generated fits from the two offline Stage 2 studies.

Uses only development identities and exact target labels. All geometry shares
the original source frame; residuals are fitted proxies, not 3-D truth errors.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

from age_protocol import _load, _path, _pin  # noqa: E402
from agemorph3d.age_geometry import (  # noqa: E402
    in_source_frame,
    source_frame,
    vector_difference_metrics,
)
from agemorph3d.age_statistics import aggregate_identity_metrics  # noqa: E402
from agemorph3d.static_mesh import projection_rotation  # noqa: E402

_METRICS = [
    "generated_to_real_neutral_rms",
    "real_increment_rms",
    "generated_increment_rms",
    "increment_residual_rms",
    "same_age_drift_rms",
    "generated_to_real_expression_rms",
    "generated_to_real_pose_degrees",
]


def _fit(root: Path, record: dict) -> dict:
    artifact = record["fit_artifact"]
    path = _path(root, artifact["path"])
    _pin(root, path, artifact["sha256"], artifact["bytes"])
    with np.load(path, allow_pickle=False) as archive:
        arrays = {
            name: archive[name].astype(np.float64)
            for name in ("vertices", "neutral_vertices", "projection")
        }
    vertices, neutral = arrays["vertices"], arrays["neutral_vertices"]
    if (
        vertices.ndim != 2
        or vertices.shape[1] != 3
        or len(vertices) < 3
        or vertices.shape != neutral.shape
        or arrays["projection"].shape != (3, 4)
        or not all(np.isfinite(value).all() for value in arrays.values())
    ):
        raise ValueError("Fit artifact contains invalid geometry or projection.")
    return arrays


def matched_comparisons(root: Path, manifest: dict, real: dict, generated: dict) -> tuple:
    """Retain all exact-age matches, including failed constituent fits."""
    if real["study"] != "longitudinal" or generated["study"] != "generated":
        raise ValueError("Expected longitudinal and generated studies in that order.")
    for role in ("detector", "reconstructor"):
        if (
            real["models"][role]["manifest_sha256"]
            != (generated["models"][role]["manifest_sha256"])
        ):
            raise ValueError("Studies must use identical model and basis versions.")
    a = {row["sample_id"]: row for row in real["fit_records"]}
    b = {row["sample_id"]: row for row in generated["fit_records"]}
    if len(a) != len(real["fit_records"]) or len(b) != len(generated["fit_records"]):
        raise ValueError("Study fit identifiers must be unique.")
    records, views = [], []
    for case in manifest["bridge_cases"]:
        source_age = case["source_age"]["value"]
        if source_age is None or case["source_status"] != "passed":
            continue
        source_id, subject = case["sample_id"], case["subject_id"]
        if case["group"] != "development":
            raise ValueError("Matched comparison cannot open non-development identities.")
        for run in case["target_runs"]:
            age = run["target_age"]
            if age == source_age:
                continue
            targets = [
                row
                for row in manifest["adult_images"]
                if (
                    row["group"] == "development"
                    and row["subject_id"] == subject
                    and row["source_age"] == age
                )
            ]
            for target in targets:
                target_id = "fgnet-" + Path(target["path"]).stem.lower()
                sam_id, same_id = (
                    f"{source_id}--sam-{age:03d}",
                    (f"{source_id}--sam-{int(source_age):03d}"),
                )
                row = dict(
                    subject_id=subject,
                    source_id=source_id,
                    real_target_id=target_id,
                    generated_target_id=sam_id,
                    same_age_id=same_id,
                    source_age=source_age,
                    target_age=age,
                )
                dependencies = [
                    a.get(source_id),
                    a.get(target_id),
                    b.get(source_id),
                    b.get(sam_id),
                    b.get(same_id),
                ]
                if any(item is None or item["status"] != "ok" for item in dependencies):
                    row.update(
                        status="failed",
                        error_code="MATCHED_FIT_UNAVAILABLE",
                        constituent_errors=[
                            None if item is None else item.get("error_code")
                            for item in dependencies
                        ],
                    )
                    records.append(row)
                    continue
                expected = [
                    case["source"],
                    target,
                    case["source"],
                    run,
                    case["same_age_control"]["output"],
                ]
                for item, pin in zip(dependencies, expected, strict=True):
                    if (
                        item["subject_id"] != subject
                        or item["input"]["sha256"] != pin["sha256"]
                        or item["input"]["path"] != pin["path"]
                    ):
                        raise ValueError("Matched fit identity or input differs from the protocol.")
                    _pin(root, _path(root, pin["path"]), pin["sha256"], pin["bytes"])
                if len({item["topology_sha256"] for item in dependencies}) != 1:
                    raise ValueError("Matched fits must share the exact ordered topology.")
                if a[source_id]["input"]["sha256"] != b[source_id]["input"]["sha256"]:
                    raise ValueError("Two studies disagree on the original source image.")
                originals = [_fit(root, item) for item in dependencies]
                source, target_fit, source_again, sam, same = originals
                if not np.array_equal(source["vertices"], source_again["vertices"]):
                    raise ValueError("Two studies produced different source fits.")
                frame = source_frame(source["vertices"])
                for fit in originals:
                    fit["neutral"] = in_source_frame(fit["neutral_vertices"], frame)
                    fit["full"] = in_source_frame(fit["vertices"], frame)
                actual_step = target_fit["neutral"] - source["neutral"]
                generated_step = sam["neutral"] - same["neutral"]
                expression = (sam["full"] - sam["neutral"]) - (
                    target_fit["full"] - target_fit["neutral"]
                )
                r1, _ = projection_rotation(sam["projection"])
                r2, _ = projection_rotation(target_fit["projection"])
                row.update(
                    status="ok",
                    error_code=None,
                    source_frame=frame,
                    generated_to_real_neutral_rms=vector_difference_metrics(
                        sam["neutral"] - target_fit["neutral"]
                    )["rms"],
                    real_increment_rms=vector_difference_metrics(actual_step)["rms"],
                    generated_increment_rms=vector_difference_metrics(generated_step)["rms"],
                    increment_residual_rms=vector_difference_metrics(generated_step - actual_step)[
                        "rms"
                    ],
                    same_age_drift_rms=vector_difference_metrics(
                        same["neutral"] - source["neutral"]
                    )["rms"],
                    generated_to_real_expression_rms=vector_difference_metrics(expression)["rms"],
                    generated_to_real_pose_degrees=float(
                        np.degrees(np.arccos(np.clip((np.trace(r1.T @ r2) - 1) / 2, -1, 1)))
                    ),
                )
                stride = max(1, int(np.ceil(len(source["neutral"]) / 1600)))
                views.append(
                    {
                        "label": f"{subject}: {source_age} -> {age}",
                        "metrics": {key: row[key] for key in _METRICS},
                        "clouds": {
                            name: fit["neutral"][::stride].round(6).tolist()
                            for name, fit in zip(
                                ("Source", "Real target", "SAM same-age", "SAM target"),
                                (source, target_fit, same, sam),
                                strict=True,
                            )
                        },
                    }
                )
                records.append(row)
    return records, views


def _html(views: list[dict]) -> str:
    data = json.dumps(views, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>AgeMorph3D 第2阶段几何研究</title><style>
body{font:16px system-ui,'Microsoft YaHei',sans-serif;background:#101821;color:#e7edf4;
max-width:1180px;margin:32px auto;padding:0 20px}h1{font-size:26px}p{line-height:1.7;color:#b7c8d9}
select,button{font:inherit;padding:8px 12px;border-radius:6px;background:#25384a;color:white}
.plots{display:flex;gap:20px;margin:20px 0;flex-wrap:wrap}canvas{background:#172430;
border:1px solid #35485a;border-radius:10px;width:540px;max-width:100%;height:auto}
#legend{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}label{cursor:pointer}
table{border-collapse:collapse;width:100%;max-width:900px}
td{padding:8px;border-bottom:1px solid #35485a}
</style><h1>真实跨龄与生成图：共同源 canonical 坐标</h1>
<p>仅为开发组的 3DDFA 拟合代理证据，不代表年龄准确率、身份保持或三维真值误差。
所有点云均移除拟合表情，并使用原始源网格的中心和尺度；目标没有独立重定位或归一化。
只列真实标签年龄与生成条件精确相同的配对。</p>
<select id="sample" aria-label="精确匹配配对"></select><div id="legend"></div>
<div class="plots"><canvas id="front" width="540" height="550"></canvas>
<canvas id="side" width="540" height="550"></canvas></div>
<table id="metrics" aria-label="拟合代理指标"></table><script>
const samples=__DATA__,colors=['#92abc0','#6ae4b3','#ffd478','#fa91a3'];
const names=['Source','Real target','SAM same-age','SAM target'];
const labels=['原始源','真实目标年龄','SAM同龄','SAM目标年龄'];
const visible=[true,true,true,true],select=document.querySelector('#sample');
samples.forEach((s,i)=>{const o=document.createElement('option');o.value=i;o.textContent=s.label;
select.append(o)});
names.forEach((name,i)=>{const label=document.createElement('label');label.style.color=colors[i];
const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=true;
checkbox.addEventListener('change',()=>{visible[i]=checkbox.checked;draw()});
label.append(checkbox,document.createTextNode(' '+labels[i]));
document.querySelector('#legend').append(label)});
function panel(id,axis,title){const c=document.querySelector(id),ctx=c.getContext('2d');
ctx.clearRect(0,0,c.width,c.height);ctx.fillStyle='#e7edf4';ctx.font='18px system-ui';
ctx.fillText(title,20,30);ctx.strokeStyle='#35485a';ctx.beginPath();ctx.moveTo(35,285);
ctx.lineTo(505,285);ctx.moveTo(270,55);ctx.lineTo(270,515);ctx.stroke();
const sample=samples[Number(select.value)||0];if(!sample)return;
names.forEach((name,i)=>{if(!visible[i])return;ctx.fillStyle=colors[i];ctx.globalAlpha=.45;
sample.clouds[name].forEach(v=>{const x=270+v[axis]*420,y=285-v[1]*420;
ctx.fillRect(x,y,1.6,1.6)})});ctx.globalAlpha=1;
ctx.fillStyle='#9cb4c8';ctx.font='12px system-ui';ctx.fillText('固定源单位 / 同一绘图比例',20,535)}
function draw(){panel('#front',0,'正面 X / Y');panel('#side',2,'侧面 Z / Y');
const table=document.querySelector('#metrics');table.replaceChildren();
const sample=samples[Number(select.value)||0];if(!sample)return;
Object.entries(sample.metrics).forEach(([key,value])=>{const row=table.insertRow();
row.insertCell().textContent=key;row.insertCell().textContent=value.toFixed(6)})}
select.addEventListener('change',draw);draw();</script></html>""".replace("__DATA__", data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--protocol-manifest", required=True)
    parser.add_argument("--longitudinal-report", required=True)
    parser.add_argument("--generated-report", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    root, created = args.root.resolve(), []
    try:
        output = _path(root, args.output_dir)
        if output.exists():
            raise FileExistsError("Output directory already exists; prior evidence is preserved.")
        paths = {
            name: _path(root, getattr(args, name))
            for name in ("protocol_manifest", "longitudinal_report", "generated_report")
        }
        manifest, real, generated = (_load(path) for path in paths.values())
        manifest_pin = _pin(root, paths["protocol_manifest"])
        for study in (real, generated):
            if study["inputs"]["protocol_manifest"]["sha256"] != manifest_pin["sha256"]:
                raise ValueError("Both studies must bind the same frozen protocol manifest.")
        records, views = matched_comparisons(root, manifest, real, generated)
        result = {
            "scope": "exact-age development-only real/generated geometry proxies",
            "research_only": True,
            "g3_complete": False,
            "service_ready": False,
            "independent_evaluation": False,
            "inputs": {key: _pin(root, path) for key, path in paths.items()},
            "records": records,
            "summary": aggregate_identity_metrics(records, _METRICS),
        }
        csv_file = io.StringIO(newline="")
        columns = [
            "subject_id",
            "source_id",
            "real_target_id",
            "source_age",
            "target_age",
            "status",
            "error_code",
            *_METRICS,
        ]
        writer = csv.DictWriter(csv_file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        payloads = {
            "report.json": json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            "matched-pairs.csv": csv_file.getvalue(),
            "comparison.html": _html(views),
        }
        output.mkdir(parents=True, exist_ok=False)
        for name, payload in payloads.items():
            with (output / name).open("x", encoding="utf-8", newline="") as stream:
                created.append(output / name)
                stream.write(payload)
        print(json.dumps(result["summary"], ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        for path in created:
            path.unlink(missing_ok=True)
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
