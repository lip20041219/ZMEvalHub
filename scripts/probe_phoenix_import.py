"""P0.1a integration probe: import a REAL ZMEvalHub fixture into Phoenix.

Uses the P0.0 contract + real de-identified fixture, verifies roundtrip
without semantic loss, and reports which fields cannot be represented.

Prereq: a local Phoenix server.
    PHOENIX_WORKING_DIR=/tmp/phx_data PHOENIX_PORT=6006 \
        uv run python -m phoenix.server.main serve
Then:
    PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006 uv run python scripts/probe_phoenix_import.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = ENDPOINT

from phoenix.client import Client  # noqa: E402

from zmevalhub.schemas.v1 import SourceRunV1  # noqa: E402

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "fixtures" / "zmai" / "real_masked_coding_agent_pass.json"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    run = SourceRunV1.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    client = Client(base_url=ENDPOINT)
    print(f"loaded fixture: {run.source}/{run.source_run_id}, cases={len(run.cases)}")

    # ---- 1. dataset: cases become examples -------------------------------
    cases = run.cases
    examples = []
    for c in cases:
        examples.append(
            {
                "input": c.input,
                "output": c.expected,
                "metadata": {
                    "case_id": c.case_id,
                    "kind": c.kind.value,
                    "tags": c.tags,
                },
            }
        )
    ds_name = f"zmeval-{run.source}-{run.source_run_id}"
    ds = client.datasets.create_dataset(name=ds_name, dataframe=None, examples=examples)
    ds_id = ds["id"] if isinstance(ds, dict) else ds.id
    check("dataset created from real fixture", bool(ds_id), f"id={ds_id}")

    # ---- 2. experiment ---------------------------------------------------
    exp = client.experiments.create(
        dataset_id=ds_id,
        experiment_name=f"{run.subject.name}-{run.source_run_id}",
        experiment_metadata={
            "zmeval.source": run.source,
            "zmeval.source_run_id": run.source_run_id,
            "zmeval.schema_version": run.schema_version,
            "zmeval.importer_version": run.importer_version,
            "zmeval.run_status": run.run_status.value,
            "zmeval.subject_name": run.subject.name,
            "zmeval.subject_model_id": run.subject.model_id,
            "zmeval.dataset_name": run.dataset.name,
            "zmeval.content_sha256": run.content_sha256(),
        },
    )
    exp_id = exp["id"] if isinstance(exp, dict) else exp.id
    check("experiment created", bool(exp_id), f"id={exp_id}")

    # ---- 3. read back examples and match by case_id ----------------------
    ds_read = client.datasets.get_dataset(dataset=ds_id)
    ex_list = (
        list(ds_read.examples) if not isinstance(ds_read, dict) else ds_read.get("examples", [])
    )
    idx = {}
    for e in ex_list:
        d = e if isinstance(e, dict) else e.__dict__
        idx[d.get("metadata", {}).get("case_id")] = d
    check(
        "examples readable by case_id",
        set(idx) == {c.case_id for c in cases},
        f"read={sorted(idx)}",
    )

    # ---- 4. log runs -----------------------------------------------------
    now = datetime.now(UTC)
    logged = 0
    for c in cases:
        ex = idx.get(c.case_id)
        if not ex:
            continue
        for a in c.attempts:
            out = json.dumps(
                {
                    "subject_outcome": a.subject_outcome.value,
                    "trace_complete": a.trace_complete,
                    "measurement_status": a.measurement_status.value,
                    "latency_ms": a.latency_ms,
                    "input_tokens": a.input_tokens,
                    "output_tokens": a.output_tokens,
                },
                ensure_ascii=False,
            )
            client.experiments.log_run(
                experiment_id=exp_id,
                dataset_example_id=ex["id"],
                output=out,
                start_time=now,
                end_time=now + timedelta(milliseconds=a.latency_ms or 1),
                repetition_number=a.attempt_index + 1,
                error=a.error_type,
            )
            logged += 1
    check(
        "attempts logged as experiment runs",
        logged == sum(len(c.attempts) for c in cases),
        f"logged={logged}",
    )

    # ---- 5. verify readback ---------------------------------------------
    exp_read = client.experiments.get_experiment(experiment_id=exp_id)
    meta = exp_read.get("experiment_metadata") or {}
    check(
        "run_status preserved",
        meta.get("zmeval.run_status") == run.run_status.value,
        f"value={meta.get('zmeval.run_status')}",
    )
    check("content_sha256 preserved", meta.get("zmeval.content_sha256") == run.content_sha256())
    check("source_run_id preserved", meta.get("zmeval.source_run_id") == run.source_run_id)
    check("subject model preserved", meta.get("zmeval.subject_model_id") == run.subject.model_id)

    tr = exp_read.get("task_runs") or []
    check("task runs exist", len(tr) >= 1, f"count={len(tr)}")

    # ---- 6. field coverage audit ----------------------------------------
    print("\n=== FIELD COVERAGE AUDIT ===")
    covered = {
        "schema_version": "experiment_metadata",
        "source": "experiment_metadata",
        "source_run_id": "experiment_metadata",
        "run_status": "experiment_metadata",
        "subject.name": "experiment_metadata",
        "subject.model_id": "experiment_metadata",
        "dataset.name": "experiment_metadata",
        "case.case_id": "example.metadata",
        "case.kind": "example.metadata",
        "case.input": "example.input",
        "case.expected": "example.output",
        "attempt.subject_outcome": "run.output (JSON)",
        "attempt.trace_complete": "run.output (JSON)",
        "attempt.latency_ms": "run.output + run timing",
    }
    not_native = {
        "subject.git_sha": "no native field; would go in metadata (null in this fixture)",
        "config_sha256": "no native field; metadata only",
        "dataset.snapshot_sha256": "Phoenix has version_id, NOT a content hash",
        "attempt.events[].sequence": "no native field; needs spans or JSON payload",
        "attempt.events[].exit_code": "no native field; needs span attribute",
        "attempt.measurement_status": "no native field; JSON payload only",
        "verdict (PASS/FAIL/UNKNOWN)": "NOT native; must use log_evaluation label",
    }
    for k, v in covered.items():
        print(f"   native-ish : {k:32} -> {v}")
    for k, v in not_native.items():
        print(f"   ADAPT      : {k:32} -> {v}")

    failed = [r for r in results if not r[1]]
    print(f"\n=== SUMMARY: {len(results) - len(failed)}/{len(results)} passed ===")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
