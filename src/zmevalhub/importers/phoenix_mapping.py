"""Map SourceRunV1 -> Phoenix dataset/experiment payloads.

Deliberately pure functions: no network, no client. This keeps the mapping
unit-testable and lets ``probe_phoenix_import.py`` do the live roundtrip.

Design notes from the P0.1a probe (Phoenix 21.0.0):

* ``datasets.create_dataset`` requires each example to carry both ``input``
  and ``output`` keys. ``CaseV1.expected`` maps to ``output``; when empty we
  send ``{}`` rather than dropping the key.
* Phoenix has dataset *versions* (``version_id``) but no content hash, so
  ZMEvalHub keeps ``snapshot_sha256`` itself.
* ``log_evaluation`` is keyed by (run, name) and OVERWRITES. Metric versions
  therefore cannot live in Phoenix alone.
"""

from __future__ import annotations

from typing import Any

from zmevalhub.schemas.v1 import AttemptV1, CaseV1, SourceRunV1

# Prefix for every passthrough key so Phoenix metadata stays attributable.
NS = "zmeval."

# Fields with no native Phoenix slot. Recorded here so nothing is silently lost.
UNSUPPORTED_FIELDS: dict[str, str] = {
    "subject.git_sha": "no native field; stored in experiment_metadata[zmeval.subject.git_sha]",
    "subject.config_sha256": "no native field; stored in experiment_metadata",
    "dataset.snapshot_sha256": (
        "Phoenix exposes version_id, not a content hash; ZMEvalHub owns the hash"
    ),
    "attempt.events": "no native per-event slot in datasets/experiments; requires OTel spans",
    "attempt.measurement_status": "stored in run.output JSON to preserve null-vs-zero semantics",
    "attempt.trace_complete": "stored in run.output JSON; drives UNKNOWN vs FAIL",
    "verdict": "not part of import; produced by rules and written via log_evaluation result.label",
}


def case_to_example(case: CaseV1) -> dict[str, Any]:
    """Convert one CaseV1 into a Phoenix dataset example."""
    return {
        "input": dict(case.input),
        # Phoenix rejects examples missing 'output'; never omit the key.
        "output": dict(case.expected),
        "metadata": {
            f"{NS}case_id": case.case_id,
            f"{NS}kind": case.kind.value,
            f"{NS}tags": list(case.tags),
        },
    }


def run_to_experiment_metadata(run: SourceRunV1) -> dict[str, Any]:
    """Everything that identifies the run and must survive a roundtrip."""
    return {
        f"{NS}schema_version": run.schema_version,
        f"{NS}source": run.source,
        f"{NS}source_run_id": run.source_run_id,
        f"{NS}importer_version": run.importer_version,
        f"{NS}run_status": run.run_status.value,
        f"{NS}content_sha256": run.content_sha256(),
        f"{NS}subject.name": run.subject.name,
        f"{NS}subject.model_id": run.subject.model_id,
        f"{NS}subject.git_sha": run.subject.git_sha,
        f"{NS}subject.config_sha256": run.subject.config_sha256,
        f"{NS}dataset.name": run.dataset.name,
        f"{NS}dataset.snapshot_sha256": run.dataset.snapshot_sha256,
    }


def attempt_to_run_output(attempt: AttemptV1) -> str:
    """Serialize the attempt facts Phoenix has no native column for.

    Kept as an explicit JSON string so ``null`` stays ``null`` — a missing
    measurement must never read back as ``0``.
    """
    import json

    return json.dumps(
        {
            "subject_outcome": attempt.subject_outcome.value,
            "trace_complete": attempt.trace_complete,
            "measurement_status": attempt.measurement_status.value,
            "latency_ms": attempt.latency_ms,
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
            "cost_amount": attempt.cost_amount,
            "cost_currency": attempt.cost_currency,
            "event_count": len(attempt.events),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def plan_import(run: SourceRunV1) -> dict[str, Any]:
    """Build the full import payload without touching the network.

    Returns a dict the live client can consume, plus a coverage report so the
    caller can see exactly what was adapted rather than dropped.
    """
    examples = [case_to_example(c) for c in run.cases]
    runs: list[dict[str, Any]] = []
    for case in run.cases:
        for attempt in case.attempts:
            runs.append(
                {
                    "case_id": case.case_id,
                    "attempt_index": attempt.attempt_index,
                    "output": attempt_to_run_output(attempt),
                    "repetition_number": attempt.attempt_index + 1,
                    "error": attempt.error_type,
                }
            )
    return {
        "dataset_name": f"zmeval-{run.source}-{run.source_run_id}",
        "examples": examples,
        "experiment_name": f"{run.subject.name}-{run.source_run_id}",
        "experiment_metadata": run_to_experiment_metadata(run),
        "runs": runs,
        "coverage": {
            "native": [
                "case.input",
                "case.expected",
                "case.case_id",
                "case.kind",
                "run identity + status",
            ],
            "adapted": sorted(UNSUPPORTED_FIELDS),
        },
    }
