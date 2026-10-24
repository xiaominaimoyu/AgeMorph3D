"""Frozen-box, isolated CPU age diagnostics with subject/source uncertainty."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
import random
import re
import sys
import sysconfig
import types
from contextlib import closing
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "_age_identity", Path(__file__).with_name("identity_evaluator_probe.py")
)
identity = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(identity)
metadata, near = identity.metadata, identity.near
Settings, ApiError, decode_image = (
    identity.Settings,
    identity.ApiError,
    identity.decode_image,
)

PROTOCOL = "agemorph3d-age-evaluator-v1"
HF_REVISION = "53393526c220e34cdd7b722b36d22b6f9e5f4241"
REPOSITORY_REVISION = "37475e3f8818b5f22448003feec3e64b01bfb188"
SOURCES = (
    *identity.SOURCES,
    "tools/age_evaluator_probe.py",
    "backend/tests/test_age_evaluator_probe.py",
)
MODEL = {
    "bytes": 115078528,
    "sha256": "96efb47051c038ebeec74b73b4253c5fd000433e5afcab7deee0bd8f3fa7bf18",
}
RELEASE = {
    "README.md": (
        3828,
        "5eb6055b7edbd4dac4f1c72825c9d40f528ea0a91849a2ae10ff8053cc0af401",
    ),
    "config.json": (
        924,
        "aa273722873361e4e77b0cea20d02311eb5bf39e521d8a09c66a5365d4ec4e9c",
    ),
    "preprocessor_config.json": (
        96,
        "e89b04cf5516faf28a434f5ee098281ef5d0e52c942b5d85b240bf89be32c567",
    ),
    "modeling_mivolo.py": (
        5255,
        "051b3b83cc1829d1d646dde2a0d65b73847afb34841c27cf61dfbdd79c7c8f4b",
    ),
    "mivolo_image_processor.py": (
        1513,
        "2e553f2b7f80223061f957e6d0ad6df009d5c5904b81836777701dce622d6311",
    ),
    "configuration_mivolo.py": (
        1462,
        "57f3d4192625d1d1d73c60ba8777de24a1a868455e90e889e68eeb84c4b14ff9",
    ),
    "vendor/LICENSE": (
        11357,
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    ),
    "vendor/mivolo/__init__.py": (
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "vendor/mivolo/model/__init__.py": (
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "vendor/mivolo/data/__init__.py": (
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "vendor/mivolo/model/create_timm_model.py": (
        4353,
        "ba6186ea436cfb359d56ae92a5b8c330c9092b4e9ac3a279a7e18f85c46d9999",
    ),
    "vendor/mivolo/model/mivolo_model.py": (
        13301,
        "1ffe5743d91b2a4519a6d2ff9e45af931472c1521b9cc2b64b492e0ade97111a",
    ),
    "vendor/mivolo/model/cross_bottleneck_attn.py": (
        4122,
        "0059a50fae8155a5f6675b318973139495629593666710a7f24c60f324aafa5d",
    ),
    "vendor/mivolo/data/misc.py": (
        8646,
        "70ce8fca4fe0633a5b6bb02115a204ff997f358d59baefac4fd68b8c6d7269cf",
    ),
}
# Keep the release table compact while exposing named pins to synthetic fixtures.
RELEASE = {name: {"bytes": size, "sha256": digest} for name, (size, digest) in RELEASE.items()}
LIMITS = {
    "image_max_bytes": 10485760,
    "image_max_pixels": 16000000,
    "model_max_bytes": 134217728,
    "source_max_bytes": 262144,
    "report_max_bytes": 2097152,
}
FALSE_FLAGS = (
    "age_quality_accepted",
    "years_calibrated",
    "independent_evaluation",
    "training_overlap_excluded",
    "legal_permission_established",
    "service_ready",
    "production_enabled",
    "g3_complete",
)
STRATA = ("20-29", "30-39", "40-49", "50-59", "60-69", "70")
GROUPS = ("development", "calibration_research")
GENERATED = ("same_age_control", "other_condition", "unknown_source_age")
BOOTSTRAP = {
    "replicates": 1000,
    "seed": 20261023,
    "unit": (
        "Subject or source, never individual images/pairs; sample effective unit metric "
        "vectors with replacement using the same draws for paired metrics"
    ),
    "stratum_seed": (
        "base seed + int(SHA256(UTF8(stratum_key)).hexdigest()[:16],16); Python random.Random"
    ),
    "stratum_key": (
        "original/{group}/{age_stratum} or within_identity/{group}/{same_age|cross_age} "
        "or generated/{category}"
    ),
    "unit_order": "Effective units sorted lexicographically by subject/source ID",
    "index_draw": (
        "For each replicate, call rng.randrange(n_effective_units) n_effective_units times; "
        "reuse that index vector across every metric"
    ),
    "interval": (
        "Percentile 2.5/97.5 with sorted linear interpolation at (n-1)*q; one effective unit "
        "gives a degenerate interval and explicit unit count; no interval for zero units"
    ),
    "interpretation": (
        "Conditional descriptive uncertainty for this cohort and scored units, "
        "not independent validation or missingness correction"
    ),
}


class EvaluationFailure(ValueError):
    pass


def _finite(value, name="prediction"):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvaluationFailure("INVALID_" + name.upper())
    return float(value)


def prediction(result):
    """Preserve the original model's floating age without a cutoff or rounding."""
    metadata._keys(result, {"age", "raw_age"}, "Age prediction")
    age, raw = _finite(result["age"]), _finite(result["raw_age"], "raw_prediction")
    # The model computes this in float32; do not demand double-precision equality.
    if not math.isclose(age, raw * 122 + 61, rel_tol=1e-6, abs_tol=1e-5):
        raise EvaluationFailure("INVALID_AGE_FORMULA")
    return {"age_estimate": age, "raw_age_estimate": raw}


def crop_bounds(face, width, height):
    """Clip an unwarped YuNet rectangle in the original EXIF-corrected frame."""
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise EvaluationFailure("INVALID_DIMENSIONS")
    if not isinstance(face, (list, tuple)) or len(face) != 15:
        raise EvaluationFailure("INVALID_FACE")
    x, y, w, h = [_finite(value, "face") for value in face[:4]]
    if w <= 0 or h <= 0:
        raise EvaluationFailure("INVALID_FACE")
    bounds = [
        max(0, math.floor(x)),
        max(0, math.floor(y)),
        min(width, math.ceil(x + w)),
        min(height, math.ceil(y + h)),
    ]
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise EvaluationFailure("EMPTY_CROP")
    return bounds


def _environment():
    packages = {}
    installation_paths = sorted(
        {str(Path(sysconfig.get_path(kind)).resolve()) for kind in ("purelib", "platlib")}
    )
    for item in importlib.metadata.distributions(path=installation_paths):
        name = re.sub(r"[-_.]+", "-", item.metadata["Name"]).lower()
        if name in packages and packages[name] != item.version:
            raise ValueError("Conflicting installed distribution versions.")
        packages[name] = item.version
    return {
        "python_version": sys.version.split()[0],
        "packages": dict(sorted(packages.items())),
    }


def _protocol(value):
    metadata._keys(
        value,
        {
            "schema_version",
            "protocol_id",
            "frozen_on",
            "scope",
            "observations",
            "cohort",
            "evaluator",
            "crop",
            "statistics",
            "limits",
            "integrity",
            "output_policy",
            "quality_threshold",
            "flags",
        },
        "Age protocol",
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["protocol_id"] != PROTOCOL
        or value["quality_threshold"] is not None
    ):
        raise ValueError("Unsupported age protocol or quality cutoff.")
    metadata._keys(value["flags"], {"research_only", *FALSE_FLAGS}, "Age flags")
    metadata._false_flags(value["flags"], FALSE_FLAGS, "Age protocol")
    if value["flags"]["research_only"] is not True or not identity._same(value["limits"], LIMITS):
        raise ValueError("Research scope and fixed limits are required.")
    evaluator = value["evaluator"]
    if evaluator != {
        "hf_revision": HF_REVISION,
        "repository_revision": REPOSITORY_REVISION,
        "device": "cpu",
        "dtype": "float32",
        "threads": 1,
        "input_size": 384,
        "body_mode": (
            "Original processor(images=[None]) normalized black tensor; retain six input channels"
        ),
        "loading": (
            "Direct fixed local classes, use_safetensors=True, local_files_only=True, "
            "torch_dtype=float32; reject missing/unexpected/mismatched/error loading entries"
        ),
        "age_formula": "raw_age_output * 122 + 61",
        "round_or_clamp": False,
        "demographic_classification_exported": False,
    }:
        raise ValueError("Age evaluator differs from the fixed algorithm.")
    if (
        value["crop"].get("padding") != 0
        or value["crop"].get("alignment")
        != "No landmark warp; original processor classification letterbox and normalization only"
        or value["crop"].get("bounds")
        != (
            "[max(0,floor(x)), max(0,floor(y)), min(width,ceil(x+w)), min(height,ceil(y+h))]; "
            "require nonempty rectangle"
        )
    ):
        raise ValueError("Only unpadded, unwarped original-frame crops are supported.")
    if value["statistics"].get("age_strata") != list(STRATA) or not identity._same(
        value["statistics"].get("bootstrap"), BOOTSTRAP
    ):
        raise ValueError("Age strata or bootstrap differs from the frozen algorithm.")
    if value["statistics"].get("generated_formulas") != {
        "prediction_shift": "generated_prediction-source_prediction",
        "condition_deviation": "generated_prediction-requested_target_age",
        "static_condition_deviation": "source_prediction-requested_target_age",
        "absolute_condition_reduction": "abs(static_condition_deviation)-abs(condition_deviation)",
    } or value["statistics"].get("paired_generated_scoring") != (
        "All conditional metrics share the pair-complete-case set: require both source "
        "and generated predictions, while retaining individual image estimates separately."
    ):
        raise ValueError("Generated paired metrics differ from the frozen algorithm.")
    cohort = value["cohort"]
    metadata._keys(
        cohort,
        {
            "groups",
            "expected_originals",
            "expected_generated",
            "expected_sources",
            "expected_unique_images",
            "expected_original_pairs",
            "expected_source_generated_pairs",
            "expected_within_identity_pairs",
            "expected_reused_detection_failures",
        },
        "Age cohort",
    )
    if cohort["groups"] != list(GROUPS):
        raise ValueError("Held-out age inference is prohibited.")
    for key, count in cohort.items():
        if key != "groups":
            metadata._integer(count, key, 0, 124750 if key.endswith("pairs") else 500)
    if value["observations"].get("real_age_scores_seen_before_freeze") is not False:
        raise ValueError("Real-age scoring must follow the prospective freeze.")


def _artifact(root, pin, maximum):
    """Hash bounded artifacts, including deliberately empty package initializers."""
    pin = identity._image_pin(pin)
    metadata._keys(pin, {"path", "bytes", "sha256"}, "Artifact")
    metadata._integer(pin["bytes"], "Artifact bytes", 0, maximum)
    digest, count = hashlib.sha256(), 0
    path = metadata._relative(root, pin["path"])
    if (
        type(pin["sha256"]) is not str
        or len(pin["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in pin["sha256"])
    ):
        raise ValueError("Artifact needs a SHA-256 pin.")
    with path.open("rb") as stream:
        while chunk := stream.read(min(1048576, maximum + 1 - count)):
            count += len(chunk)
            if count > maximum or count > pin["bytes"]:
                raise ValueError("Artifact exceeds its declared bound.")
            digest.update(chunk)
    if count != pin["bytes"] or digest.hexdigest() != pin["sha256"]:
        raise ValueError("Artifact pin mismatch: " + pin["path"])
    return path


def _artifacts(root, source_acquisition, model_acquisition):
    if (
        source_acquisition.get("hf_revision") != HF_REVISION
        or source_acquisition.get("repository_revision") != REPOSITORY_REVISION
        or model_acquisition.get("hf_revision") != HF_REVISION
    ):
        raise ValueError("Only the fixed MiVOLO revisions are supported.")
    model_pin = identity._image_pin(model_acquisition["model"])
    if {key: model_pin[key] for key in MODEL} != MODEL or Path(
        model_pin["path"]
    ).name != "model.safetensors":
        raise ValueError("Unsupported MiVOLO weights.")
    base = _artifact(root, model_pin, LIMITS["model_max_bytes"]).parent
    base_relative = base.relative_to(root).as_posix()
    artifacts, names = [], set()
    for item in metadata._list(source_acquisition.get("artifacts"), "Source artifacts", 30):
        pin = identity._image_pin(item)
        path = metadata._relative(root, pin["path"])
        if not path.is_relative_to(base):
            raise ValueError("MiVOLO source artifact escapes the fixed model directory.")
        name = path.relative_to(base).as_posix()
        if (
            name not in RELEASE
            or name in names
            or {key: pin[key] for key in RELEASE[name]} != RELEASE[name]
        ):
            raise ValueError("Unsupported, duplicate or changed MiVOLO source: " + name)
        _artifact(root, pin, LIMITS["source_max_bytes"])
        names.add(name)
        artifacts.append(pin)
    if names != set(RELEASE):
        raise ValueError("The complete fixed 14-source snapshot is required.")
    pointer_pin = identity._image_pin(model_acquisition["official_pointer"])
    if pointer_pin["path"] != base_relative + "/model-lfs-pointer.txt":
        raise ValueError("Model pointer must be in the same fixed directory.")
    pointer = _artifact(root, pointer_pin, 1024).read_text(encoding="utf-8")
    if pointer != (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{MODEL['sha256']}\nsize {MODEL['bytes']}\n"
    ):
        raise ValueError("Official LFS pointer differs from the supported model.")
    return base, model_pin, artifacts, pointer_pin


class CpuAgePredictor:
    """Original fixed local classes, six-channel face/black-body CPU float32."""

    def __init__(self, base):
        self.model = None
        self.environment = _environment()
        os.environ.update(
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            CUDA_VISIBLE_DEVICES="",
            HF_HOME=str(base / "hf-cache"),
            TOKENIZERS_PARALLELISM="false",
        )
        import numpy as np
        import torch

        self.np, self.torch = np, torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        sys.path.insert(0, str(base / "vendor"))
        for name, module in tuple(sys.modules.items()):
            if name == "mivolo" or name.startswith("mivolo."):
                source = getattr(module, "__file__", None)
                if not source or not Path(source).resolve().is_relative_to(base / "vendor"):
                    raise ValueError("A conflicting MiVOLO module is already imported.")
        package = types.ModuleType("_agemorph_age_fixed_mivolo")
        package.__path__ = [str(base)]
        sys.modules[package.__name__] = package
        config_module = importlib.import_module(package.__name__ + ".configuration_mivolo")
        model_module = importlib.import_module(package.__name__ + ".modeling_mivolo")
        processor_module = importlib.import_module(package.__name__ + ".mivolo_image_processor")
        for module, filename in (
            (config_module, "configuration_mivolo.py"),
            (model_module, "modeling_mivolo.py"),
            (processor_module, "mivolo_image_processor.py"),
        ):
            if Path(module.__file__).resolve() != base / filename:
                raise ValueError("A cached MiVOLO class comes from a different source directory.")
        config = config_module.MiVOLOConfig.from_pretrained(base, local_files_only=True)
        try:
            self.model, info = model_module.MiVOLOForImageClassification.from_pretrained(
                base,
                config=config,
                torch_dtype=torch.float32,
                use_safetensors=True,
                local_files_only=True,
                output_loading_info=True,
            )
            if any(
                info.get(key)
                for key in (
                    "missing_keys",
                    "unexpected_keys",
                    "mismatched_keys",
                    "error_msgs",
                )
            ):
                raise ValueError("Non-strict MiVOLO loading.")
            if not all(
                p.device.type == "cpu" and p.dtype == torch.float32 for p in self.model.parameters()
            ):
                raise ValueError("MiVOLO parameters must be CPU float32.")
            self.model.eval()
            options = metadata._json(metadata._read(base / "preprocessor_config.json"))
            self.processor = processor_module.MiVOLOImageProcessor(**options)
            self.body = self.processor(images=[None])["pixel_values"]
            if list(self.body.shape) != [1, 3, 384, 384]:
                raise ValueError("MiVOLO absent-body tensor shape differs.")
        except Exception:
            self.close()
            raise

    def predict(self, rgb):
        bgr = self.np.asarray(rgb)[:, :, ::-1].copy()
        face = self.processor(images=[bgr])["pixel_values"]
        if list(face.shape) != [1, 3, 384, 384]:
            raise EvaluationFailure("INVALID_FACE_TENSOR")
        with self.torch.inference_mode():
            output = self.model(faces_input=face, body_input=self.body)
            if list(output.age_output.shape) != [1, 1] or list(output.raw_age_output.shape) != [
                1,
                1,
            ]:
                raise EvaluationFailure("INVALID_AGE_OUTPUT")
            # Export only the two age scalars; demographic logits never leave this method.
            return {
                "age": output.age_output.item(),
                "raw_age": output.raw_age_output.item(),
            }

    def close(self):
        self.model = None
        if hasattr(self, "body"):
            self.body = None
        gc.collect()


def _percentile(values, quantile):
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(rows, key, metrics, protocol, *, squared_metric=None):
    """Rows are (unit, metric-vector-or-None); bootstrap entire unit vectors."""
    units = {}
    for unit, vector in rows:
        item = units.setdefault(unit, {"requested": 0, "vectors": []})
        item["requested"] += 1
        if vector is not None:
            if set(vector) != set(metrics):
                raise ValueError("Metric vector shape differs.")
            item["vectors"].append({name: _finite(vector[name], "metric") for name in metrics})
    details = []
    for unit, item in sorted(units.items()):
        vectors = item["vectors"]
        details.append(
            {
                "unit": unit,
                "requested": item["requested"],
                "scored": len(vectors),
                "null": item["requested"] - len(vectors),
                "mean": {
                    name: math.fsum(vector[name] for vector in vectors) / len(vectors)
                    if vectors
                    else None
                    for name in metrics
                },
            }
        )
    effective = [item["mean"] for item in details if item["scored"]]

    def macro(vectors):
        result = {
            name: math.fsum(vector[name] for vector in vectors) / len(vectors) if vectors else None
            for name in metrics
        }
        if squared_metric is not None:
            result["rmse"] = math.sqrt(result[squared_metric]) if vectors else None
        return result

    config = protocol["statistics"]["bootstrap"]
    seed = config["seed"] + int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    estimates = macro(effective)
    samples = {name: [] for name in estimates}
    if effective:
        for _ in range(config["replicates"]):
            sampled = [effective[rng.randrange(len(effective))] for _ in effective]
            for name, value in macro(sampled).items():
                samples[name].append(value)
    return {
        "requested": len(rows),
        "scored": sum(item["scored"] for item in details),
        "null": sum(item["null"] for item in details),
        "eligible_units": len(details),
        "effective_units": len(effective),
        "units": details,
        "macro": estimates,
        "bootstrap": {
            "replicates": config["replicates"],
            "seed": seed,
            "unit": "subject_or_source",
            "intervals": {
                name: [_percentile(values, 0.025), _percentile(values, 0.975)] if values else None
                for name, values in samples.items()
            },
        },
    }


def _error_vector(error):
    return {"mae": abs(error), "bias": error, "mse": error * error}


def aggregate_originals(records, protocol):
    results = []
    for group in GROUPS:
        for stratum in ("all", *STRATA):
            rows = []
            for record in records:
                label = record["source_age_label"]
                if "original" not in record["roles"] or record["group"] != group:
                    continue
                age_stratum = "70" if label == 70 else f"{label // 10 * 10}-{label // 10 * 10 + 9}"
                if stratum != "all" and age_stratum != stratum:
                    continue
                error = record["age_estimate"] - label if record["status"] == "ok" else None
                rows.append(
                    (
                        record["subject_id"],
                        _error_vector(error) if error is not None else None,
                    )
                )
            results.append(
                {
                    "group": group,
                    "age_stratum": stratum,
                    **summarize(
                        rows,
                        f"original/{group}/{stratum}",
                        ("mae", "bias", "mse"),
                        protocol,
                        squared_metric="mse",
                    ),
                }
            )
    return results


def score_within(requests, records):
    pairs = []
    for request in requests:
        if request["type"] != "original_comparison" or not request["category"].startswith(
            "same_identity_"
        ):
            continue
        left, right = records[request["left_id"]], records[request["right_id"]]
        expected = right["source_age_label"] - left["source_age_label"]
        predicted = (
            right["age_estimate"] - left["age_estimate"]
            if left["status"] == right["status"] == "ok"
            else None
        )
        pairs.append(
            {
                **request,
                "left_status": left["status"],
                "right_status": right["status"],
                "status": "scored" if predicted is not None else "failed",
                "label_delta": expected,
                "prediction_delta": predicted,
                "prediction_delta_error": predicted - expected if predicted is not None else None,
            }
        )
    return pairs


def score_generated(requests, records):
    pairs = []
    for request in requests:
        if request["type"] != "source_generated_comparison":
            continue
        left, right = records[request["left_id"]], records[request["right_id"]]
        target = right["target_condition"]
        values = dict.fromkeys(
            (
                "prediction_shift",
                "condition_deviation",
                "static_condition_deviation",
                "absolute_condition_reduction",
            )
        )
        if left["status"] == right["status"] == "ok":
            generated, static = (
                right["age_estimate"] - target,
                left["age_estimate"] - target,
            )
            values.update(
                prediction_shift=right["age_estimate"] - left["age_estimate"],
                condition_deviation=generated,
                static_condition_deviation=static,
                absolute_condition_reduction=abs(static) - abs(generated),
            )
        pairs.append(
            {
                **request,
                "left_status": left["status"],
                "right_status": right["status"],
                "status": "scored" if values["prediction_shift"] is not None else "failed",
                "requested_target_age": target,
                "source_age_label": left["source_age_label"],
                **values,
            }
        )
    return pairs


def aggregate_within(pairs, protocol):
    return [
        {
            "group": group,
            "category": category,
            **summarize(
                [
                    (
                        pair["unit"],
                        _error_vector(pair["prediction_delta_error"])
                        if pair["status"] == "scored"
                        else None,
                    )
                    for pair in pairs
                    if pair["group"] == group and pair["category"] == "same_identity_" + category
                ],
                f"within_identity/{group}/{category}",
                ("mae", "bias", "mse"),
                protocol,
                squared_metric="mse",
            ),
        }
        for group in GROUPS
        for category in ("same_age", "cross_age")
    ]


def aggregate_generated(pairs, protocol):
    metrics = (
        "prediction_shift",
        "condition_deviation",
        "static_condition_deviation",
        "absolute_condition_reduction",
    )
    return [
        {
            "category": category,
            **summarize(
                [
                    (
                        pair["unit"],
                        {name: pair[name] for name in metrics}
                        if pair["status"] == "scored"
                        else None,
                    )
                    for pair in pairs
                    if pair["category"] == category
                ],
                f"generated/{category}",
                metrics,
                protocol,
            ),
        }
        for category in GENERATED
    ]


def _detections(images, report, plan, counts, cohort):
    if (
        report.get("protocol_id") != identity.PROTOCOL
        or report.get("integrity_status") != "passed"
        or report.get("research_only") is not True
        or report.get("cohort_counts") != counts
    ):
        raise ValueError("Pinned identity report scope, integrity or cohort differs.")
    metadata._false_flags(report, identity.FALSE_FLAGS, "Frozen identity report")
    for role in (
        "age_protocol",
        "n0_manifest",
        "registration_report",
        "identity_protocol",
    ):
        if plan[role] not in report.get("inputs", []):
            raise ValueError("Identity report does not bind the same metadata inputs.")
    records = report.get("records")
    if not isinstance(records, list) or len(records) != len(images):
        raise ValueError("Frozen detection record count differs.")
    failures = 0
    for image, record in zip(images, records, strict=True):
        if any(record.get(key) != value for key, value in image.items()):
            raise ValueError("Frozen identity image provenance differs.")
        for phase in ("initial_source_check", "final_source_check"):
            expected = {
                **image["source"],
                "verification": "verified",
                "matches_declared": True,
            }
            if record.get(phase) != expected:
                raise ValueError("Frozen detection image was not integrity verified.")
        if record.get("source_changed") is not False:
            raise ValueError("Frozen detection source drift is prohibited.")
        status = record.get("status")
        metadata._text(status, "Frozen detector status", 100)
        if status == "ok":
            width, height = record.get("width"), record.get("height")
            metadata._integer(width, "Frozen width", 1, LIMITS["image_max_pixels"])
            metadata._integer(height, "Frozen height", 1, LIMITS["image_max_pixels"])
            if width * height > LIMITS["image_max_pixels"]:
                raise ValueError("Frozen dimensions exceed the pixel bound.")
            identity.map_face(record.get("face"), (width, height), (width, height))
            crop_bounds(record["face"], width, height)
        else:
            failures += 1
    if failures != cohort["expected_reused_detection_failures"]:
        raise ValueError("Reused detector failure denominator differs.")
    return records


def build_report(root: Path, plan_path: Path, evaluator_factory=CpuAgePredictor):
    root, plan_path = (
        Path(root).resolve(strict=True),
        Path(plan_path).resolve(strict=True),
    )
    if not plan_path.is_relative_to(root) or plan_path.suffix != ".json":
        raise ValueError("Study plan must be workspace JSON metadata.")
    raw = metadata._read(plan_path)
    plan = metadata._json(raw)
    roles = (
        "protocol",
        "age_protocol",
        "n0_manifest",
        "registration_report",
        "identity_protocol",
        "identity_report",
        "source_acquisition",
        "model_acquisition",
        "environment",
    )
    metadata._keys(plan, {"protocol_id", *roles, "source_files"}, "Age study plan")
    if plan["protocol_id"] != PROTOCOL or len({plan[role]["path"] for role in roles}) != len(roles):
        raise ValueError("Unsupported protocol or duplicate metadata roles.")
    inputs = metadata._Inputs(root)
    inputs.read(
        {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    values = {role: metadata._json(inputs.read(plan[role])) for role in roles}
    inputs.many(plan["source_files"], "Source files")
    source_pins = {pin["path"]: pin for pin in plan["source_files"]}
    if set(source_pins) != set(SOURCES):
        raise ValueError("The exact twelve implementation/dependency sources must be pinned.")
    actual_root = Path(__file__).resolve().parents[1]
    for name in SOURCES:
        if (
            source_pins[name]["sha256"]
            != hashlib.sha256(metadata._read(actual_root / name)).hexdigest()
        ):
            raise ValueError("Running implementation differs from pinned source files.")
    protocol = values["protocol"]
    _protocol(protocol)
    identity._protocol(values["identity_protocol"])
    n0 = values["n0_manifest"]
    metadata._n0(values["age_protocol"], n0, n0.get("summary"), plan["age_protocol"])
    images, requests, counts = identity._requests(
        root,
        n0,
        values["registration_report"],
        plan["n0_manifest"],
        values["identity_protocol"]["cohort"],
    )
    if any(protocol["cohort"].get(key) != value for key, value in counts.items()):
        raise ValueError("Age cohort differs from the frozen identity request cohort.")
    detections = _detections(images, values["identity_report"], plan, counts, protocol["cohort"])
    if (
        sum(
            request["type"] == "original_comparison"
            and request["category"].startswith("same_identity_")
            for request in requests
        )
        != protocol["cohort"]["expected_within_identity_pairs"]
    ):
        raise ValueError("Within-identity requested denominator differs.")
    base, model_pin, source_artifacts, pointer_pin = _artifacts(
        root, values["source_acquisition"], values["model_acquisition"]
    )
    expected_environment = values["environment"]
    metadata._keys(expected_environment, {"python_version", "packages"}, "Environment")
    if not identity._same(_environment(), expected_environment):
        raise ValueError("Installed environment differs from the frozen environment.")
    records, evaluator = [], None
    settings = Settings(
        max_image_bytes=LIMITS["image_max_bytes"],
        max_image_pixels=LIMITS["image_max_pixels"],
    )
    try:
        evaluator = evaluator_factory(base)
        if not identity._same(evaluator.environment, expected_environment):
            raise ValueError("Age evaluator environment differs from its pin.")
        for image, detection in zip(images, detections, strict=True):
            initial, snapshot = near._snapshot(root, image["source"])
            record = {
                **image,
                "status": initial["verification"],
                "initial_source_check": initial,
                "reused_detection_status": detection["status"],
                "age_estimate": None,
                "raw_age_estimate": None,
            }
            if snapshot is not None:
                if detection["status"] != "ok":
                    record["status"] = detection["status"]
                else:
                    try:
                        media = {
                            ".jpg": "image/jpeg",
                            ".jpeg": "image/jpeg",
                            ".png": "image/png",
                            ".webp": "image/webp",
                        }[Path(image["source"]["path"]).suffix.lower()]
                        with closing(decode_image(snapshot, media, settings)) as rgb:
                            if (rgb.width, rgb.height) != (
                                detection["width"],
                                detection["height"],
                            ):
                                raise EvaluationFailure("DIMENSIONS_DIFFER")
                            bounds = crop_bounds(detection["face"], rgb.width, rgb.height)
                            with closing(rgb.crop(tuple(bounds))) as crop:
                                result = prediction(evaluator.predict(crop))
                            record.update(
                                status="ok",
                                width=rgb.width,
                                height=rgb.height,
                                reused_bbox=detection["face"][:4],
                                crop_bounds=bounds,
                                **result,
                            )
                    except ApiError as error:
                        record["status"] = error.code
                    except EvaluationFailure as error:
                        record["status"] = str(error)
                    except (
                        RuntimeError,
                        TypeError,
                        ValueError,
                        OverflowError,
                        OSError,
                    ) as error:
                        record.update(
                            status="AGE_EVALUATOR_FAILED",
                            failure_type=type(error).__name__,
                        )
            records.append(record)

        def statistics():
            within, generated = (
                score_within(requests, records),
                score_generated(requests, records),
            )
            return (
                within,
                generated,
                aggregate_originals(records, protocol),
                aggregate_within(within, protocol),
                aggregate_generated(generated, protocol),
            )

        within, generated, originals_summary, within_summary, generated_summary = statistics()
        integrity = True
        # Each estimate can be invalidated only once. Recheck after recomputation,
        # too, so an image changing during replacement bootstraps is also removed.
        for _ in range(len(records) + 1):
            changed = False
            for record in records:
                final, _ = near._snapshot(root, record["source"])
                record["final_source_check"] = final
                record["source_changed"] = (
                    record.get("source_changed", False) or final != record["initial_source_check"]
                )
                if record["source_changed"] and record["status"] != "source_changed":
                    record["status_before_source_change"] = record["status"]
                    record.update(
                        status="source_changed",
                        age_estimate=None,
                        raw_age_estimate=None,
                    )
                    changed = True
                integrity &= (
                    final["matches_declared"]
                    and record["initial_source_check"]["matches_declared"]
                    and not record["source_changed"]
                )
            if not changed:
                break
            within, generated, originals_summary, within_summary, generated_summary = statistics()
        _artifacts(root, values["source_acquisition"], values["model_acquisition"])
        inputs.verify()
        for name in SOURCES:
            if (
                source_pins[name]["sha256"]
                != hashlib.sha256(metadata._read(actual_root / name)).hexdigest()
            ):
                raise ValueError("Running implementation changed during scoring.")
        if not identity._same(_environment(), expected_environment) or not identity._same(
            evaluator.environment, expected_environment
        ):
            raise ValueError("Age environment changed during scoring.")
    finally:
        if evaluator is not None:
            evaluator.close()
    successful = sum(record["status"] == "ok" for record in records)

    def pair_counts(pairs):
        return {
            "requested": len(pairs),
            "scored": sum(pair["status"] == "scored" for pair in pairs),
            "failed": sum(pair["status"] != "scored" for pair in pairs),
        }

    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "research_only": True,
        **dict.fromkeys(FALSE_FLAGS, False),
        "quality_threshold": None,
        "integrity_status": "passed" if integrity else "failed",
        "execution_status": "complete"
        if successful == len(records) and integrity
        else "completed_with_failures",
        "images_or_crops_written": False,
        "demographic_classification_exported": False,
        "holdout_age_predictions_extracted": False,
        "models_closed": True,
        "environment": expected_environment,
        "inputs": [inputs.pins[path] for path in sorted(inputs.pins)],
        "model_pin": model_pin,
        "source_artifact_pins": source_artifacts,
        "model_pointer_pin": pointer_pin,
        "cohort_counts": {**counts, "expected_within_identity_pairs": len(within)},
        "image_counts": {
            "requested": len(records),
            "successful": successful,
            "failed": len(records) - successful,
        },
        "within_identity_pair_counts": pair_counts(within),
        "generated_pair_counts": pair_counts(generated),
        "records": records,
        "within_identity_pairs": within,
        "generated_pairs": generated,
        "original_aggregates": originals_summary,
        "within_identity_aggregates": within_summary,
        "generated_aggregates": generated_summary,
        "upstream_source_failures": values["identity_report"].get("upstream_source_failures", []),
        "final_source_check_phase": "after_all_inference_pair_scoring_macro_and_bootstrap",
        "limits": [
            (
                "Research filename ages are unverified labels; "
                "SAM target ages are conditions, never truth."
            ),
            (
                "Generated age shifts are evaluator diagnostics, not calibrated years, "
                "individual predictions or G3 acceptance."
            ),
            (
                "Intervals condition on scored units; missingness, training overlap "
                "and age-domain bias remain unresolved."
            ),
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        output = metadata._relative(root, args.output_dir)
        allowed = (root / "output/research").resolve()
        if (
            not output.is_relative_to(allowed)
            or output == allowed
            or not allowed.is_relative_to(root)
        ):
            raise ValueError("Output must be a new descendant of workspace output/research.")
        if output.exists():
            raise FileExistsError("Output already exists; previous evidence is preserved.")
        plan = (
            args.study_plan
            if args.study_plan.is_absolute()
            else metadata._relative(root, args.study_plan.as_posix())
        )
        report = build_report(root, plan)
        raw = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode(
            "utf-8"
        )
        if len(raw) > LIMITS["report_max_bytes"]:
            raise ValueError("Report exceeds the frozen 2 MiB bound; nothing was published.")
        output.mkdir(parents=True, exist_ok=False)
        with (output / "report.json").open("xb") as stream:
            stream.write(raw)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "integrity_status",
                        "execution_status",
                        "image_counts",
                        "within_identity_pair_counts",
                        "generated_pair_counts",
                    )
                }
            )
        )
        return 0 if report["execution_status"] == "complete" else 1
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
    ) as error:
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
