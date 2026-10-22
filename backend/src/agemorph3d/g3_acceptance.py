"""Pure offline, itemized G3 policy; this module grants no service authority.

Callers own evidence provenance, hashes, evaluation scope and review. A passed
check is a caller-supplied assessment, not independent verification by this
policy. Missing evidence fails closed; even an all-passed report cannot load a
model, change production capabilities or authorize a production request.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

Status = Literal["passed", "failed", "missing"]

COMMON_REQUIREMENTS = (
    "asset_license",
    "evaluation_protocol",
    "independent_evaluation",
    "identity_quality",
    "strict_reconstruction_acceptance",
)
COMPONENT_REQUIREMENTS = MappingProxyType(
    {
        "shape": COMMON_REQUIREMENTS
        + (
            "shape_route",
            "shape_year_calibration",
            "shape_source_reset",
            "shape_quality",
            "shape_continuity",
        ),
        "texture": COMMON_REQUIREMENTS
        + (
            "target_uv_registration",
            "texture_source_reset",
            "texture_quality",
            "texture_age_quality",
            "rendered_texture_continuity",
        ),
        "continuity": COMMON_REQUIREMENTS
        + (
            "shape_continuity",
            "rendered_texture_continuity",
            "shape_source_reset",
            "texture_source_reset",
        ),
        "identity": COMMON_REQUIREMENTS,
    }
)
SERVICE_REQUIREMENTS = COMMON_REQUIREMENTS + (
    "real_service_integration",
    "service_resource_lifecycle",
    "service_performance",
)
CHECK_IDS = tuple(
    dict.fromkeys(
        check_id
        for requirements in (*COMPONENT_REQUIREMENTS.values(), SERVICE_REQUIREMENTS)
        for check_id in requirements
    )
)


@dataclass(frozen=True)
class Check:
    """One bounded assessment, with immutable references to caller-owned evidence."""

    status: Status
    reason: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"passed", "failed", "missing"}:
            raise ValueError("Check status must be passed, failed or missing.")
        if (
            type(self.reason) is not str
            or not self.reason.strip()
            or len(self.reason) > 2000
            or "\x00" in self.reason
        ):
            raise ValueError("Check reason must be nonempty text of at most 2000 characters.")
        if type(self.evidence) is not tuple or len(self.evidence) > 64:
            raise ValueError("Check evidence must be a tuple of at most 64 evidence IDs.")
        if any(
            type(evidence_id) is not str
            or not evidence_id.strip()
            or len(evidence_id) > 128
            or "\x00" in evidence_id
            for evidence_id in self.evidence
        ):
            raise ValueError("Evidence IDs must be nonempty text of at most 128 characters.")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("Evidence IDs in a check must be unique.")
        if self.status != "missing" and not self.evidence:
            raise ValueError("Passed and failed checks require evidence IDs.")


def _check_record(check: Check) -> dict:
    return {"status": check.status, "reason": check.reason, "evidence": list(check.evidence)}


def _group(requirements: tuple[str, ...], checks: Mapping[str, Check]) -> dict:
    blockers = [
        {"check_id": check_id, **_check_record(checks[check_id])}
        for check_id in requirements
        if checks[check_id].status != "passed"
    ]
    status = (
        "failed"
        if any(item["status"] == "failed" for item in blockers)
        else "missing"
        if blockers
        else "passed"
    )
    return {
        "status": status,
        "accepted": status == "passed",
        "required_checks": list(requirements),
        "blockers": blockers,
    }


def evaluate_g3(checks: Mapping[str, Check]) -> dict:
    """Evaluate fixed dependencies without reading files or changing any service.

    Omitted checks are missing. Invalid IDs or values are rejected rather than
    ignored. Component acceptance means only that every caller-supplied check in
    that component's fixed policy is passed; consumers must retain that scope.
    """
    if not isinstance(checks, Mapping):
        raise ValueError("G3 checks must be a mapping from fixed check IDs to Check values.")
    for check_id, check in checks.items():
        if type(check_id) is not str or check_id not in CHECK_IDS:
            raise ValueError("Unknown G3 check ID.")
        if not isinstance(check, Check):
            raise ValueError("G3 check values must be Check instances.")
    complete = {
        check_id: checks.get(
            check_id, Check(status="missing", reason="Required evidence has not been supplied.")
        )
        for check_id in CHECK_IDS
    }
    components = {
        name: _group(requirements, complete)
        for name, requirements in COMPONENT_REQUIREMENTS.items()
    }
    service = _group(SERVICE_REQUIREMENTS, complete)
    return {
        "schema_version": 1,
        "policy_id": "g3-itemized-v1",
        "checks": {check_id: _check_record(check) for check_id, check in complete.items()},
        "components": components,
        "service": service,
        "candidate_capabilities": {
            "age_morph": components["shape"]["accepted"],
            "age_texture": components["texture"]["accepted"],
        },
        "g3_complete": service["accepted"]
        and all(component["accepted"] for component in components.values()),
        "production_enabled": False,
    }
