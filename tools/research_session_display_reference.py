"""Independent saved-PNG reference for session display and exported atlas checks.

This script imports neither the browser sampler nor model/processor helpers.
It is representation verification, never an age or identity quality assessment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        if image.format != "PNG" or image.size != (256, 256) or image.mode != "RGBA":
            raise ValueError("A native256x256RGBA atlas PNG is required.")
        return np.asarray(image).copy()


def sample(a: np.ndarray, b: np.ndarray, weight: float) -> np.ndarray:
    if weight == 0:
        return a.copy()
    if weight == 1:
        return b.copy()
    ar, br = a[:, :, :3].astype(np.float64) / 255, b[:, :, :3].astype(np.float64) / 255
    aa, ba = a[:, :, 3:4].astype(np.float64) / 255, b[:, :, 3:4].astype(np.float64) / 255
    al = np.where(ar <= 0.04045, ar / 12.92, ((ar + 0.055) / 1.055) ** 2.4)
    bl = np.where(br <= 0.04045, br / 12.92, ((br + 0.055) / 1.055) ** 2.4)
    alpha = (1 - weight) * aa + weight * ba
    premultiplied = (1 - weight) * aa * al + weight * ba * bl
    color = np.zeros_like(premultiplied)
    np.divide(premultiplied, alpha, out=color, where=alpha != 0)
    color = np.clip(color, 0, 1)
    encoded = np.where(color <= 0.0031308, color * 12.92, 1.055 * color ** (1 / 2.4) - 0.055)
    result = np.concatenate(
        (np.rint(np.clip(encoded, 0, 1) * 255), np.rint(np.clip(alpha, 0, 1) * 255)), axis=2
    ).astype(np.uint8)
    result[result[:, :, 3] == 0] = 0
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--source-age", type=float, required=True)
    parser.add_argument("--target-condition", type=int, required=True)
    parser.add_argument("--ages-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export-manifest", type=Path)
    args = parser.parse_args()
    ages = json.loads(args.ages_json)
    if (
        not 20 <= args.source_age < args.target_condition <= 70
        or not isinstance(ages, list)
        or not 1 <= len(ages) <= 64
    ):
        raise ValueError(
            "Use bounded increasing source/target anchors and explicit display values."
        )
    a, b = rgba(args.source), rgba(args.target)
    for anchor in (a, b):
        if not np.isin(anchor[:, :, 3], (0, 255)).all() or np.any(anchor[anchor[:, :, 3] == 0]):
            raise ValueError("Raw anchor unknownRGBA or binary alpha differs.")
    args.output.mkdir(parents=True, exist_ok=False)
    exports = [] if args.export_manifest is None else json.loads(args.export_manifest.read_bytes())
    records = []
    for index, age in enumerate(ages):
        if type(age) not in (int, float) or not args.source_age <= age <= args.target_condition:
            raise ValueError("Display reference cannot extrapolate or reinterpret an age.")
        pixels = sample(a, b, (age - args.source_age) / (args.target_condition - args.source_age))
        path = args.output / f"frame-{index:02d}.png"
        with path.open("xb") as stream:
            Image.fromarray(pixels).save(stream, format="PNG")
        row = {
            "age": age,
            "rgba_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
            "reference_png": str(path.resolve()),
            "partial_alpha_texels": int(
                np.count_nonzero((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 255))
            ),
        }
        comparisons = []
        for item in exports:
            if item["age"] != age:
                continue
            actual = rgba(Path(item["path"]))
            difference = np.abs(actual.astype(np.int16) - pixels.astype(np.int16))
            partial = (pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 255)
            assert np.array_equal(actual[:, :, 3], pixels[:, :, 3])
            assert not np.any(actual[actual[:, :, 3] == 0])
            assert not np.any(difference[~partial])
            assert not np.any(difference)
            comparisons.append(
                {
                    "path": item["path"],
                    "max_rgb_error": int(difference[:, :, :3].max()),
                    "alpha_exact": True,
                    "nonpartial_exact": True,
                    "unknown_rgba_zero": True,
                    "rgba_exact": True,
                }
            )
        row["export_comparisons"] = comparisons
        records.append(row)
    report = {
        "status": "passed",
        "research_only": True,
        "g3_complete": False,
        "quality_accepted": False,
        "records": records,
        "core_helpers_imported": False,
        "model_inference_executed": False,
    }
    with (args.output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": "passed", "cases": len(records), "exports": len(exports)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
