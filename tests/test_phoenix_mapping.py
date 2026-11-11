"""Unit tests for the SourceRunV1 -> Phoenix mapping.

These run offline (no Phoenix server). The live roundtrip lives in
``scripts/probe_phoenix_import.py`` because it needs a running server.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zmevalhub.importers.phoenix_mapping import (
    NS,
    UNSUPPORTED_FIELDS,
    attempt_to_run_output,
    case_to_example,
    plan_import,
    run_to_experiment_metadata,
)
from zmevalhub.schemas.v1 import SourceRunV1

FIXTURES = Path(__file__).parent.parent / "fixtures"
ZMAI = FIXTURES / "zmai" / "real_masked_coding_agent_pass.json"
ZMWIKI = FIXTURES / "zmwiki" / "real_masked_rag_multihop.json"
UNKNOWN_CASE = FIXTURES / "synthetic" / "synthetic_unknown_evidence.json"


def load(path: Path) -> SourceRunV1:
    return SourceRunV1.model_validate_json(path.read_text(encoding="utf-8"))


# ------------------------------------------------------- example structure
def test_every_example_has_input_and_output_keys() -> None:
    """Phoenix rejects examples missing 'output', so the key must always exist."""
    for path in (ZMAI, ZMWIKI):
        run = load(path)
        for case in run.cases:
            ex = case_to_example(case)
            assert "input" in ex
            assert "output" in ex


def test_empty_expected_still_emits_output_key() -> None:
    run = load(ZMAI)
    case = run.cases[0].model_copy(update={"expected": {}})
    ex = case_to_example(case)
    assert ex["output"] == {}


def test_case_metadata_is_namespaced() -> None:
    run = load(ZMAI)
    meta = case_to_example(run.cases[0])["metadata"]
    assert meta[f"{NS}case_id"] == run.cases[0].case_id
    assert meta[f"{NS}kind"] == "coding_agent"
    assert all(k.startswith(NS) for k in meta)


def test_rag_case_maps_to_example() -> None:
    run = load(ZMWIKI)
    ex = case_to_example(run.cases[0])
    assert "question" in ex["input"]
    assert ex["metadata"][f"{NS}kind"] == "rag_agent"


# ---------------------------------------------------- experiment metadata
def test_experiment_metadata_carries_run_identity() -> None:
    run = load(ZMAI)
    meta = run_to_experiment_metadata(run)
    assert meta[f"{NS}source"] == "zmai"
    assert meta[f"{NS}source_run_id"] == run.source_run_id
    assert meta[f"{NS}run_status"] == "SUCCEEDED"
    assert meta[f"{NS}content_sha256"] == run.content_sha256()
    assert meta[f"{NS}subject.name"] == "ZMAI"


def test_experiment_metadata_preserves_nulls() -> None:
    """A null git_sha must stay null, not become '' or 'unknown'."""
    run = load(ZMAI)
    meta = run_to_experiment_metadata(run)
    assert meta[f"{NS}subject.git_sha"] is None
    assert meta[f"{NS}dataset.snapshot_sha256"] is None


# --------------------------------------------------------------- run output
def test_run_output_preserves_missing_measurements_as_null() -> None:
    """The core no-fabrication rule: absent numbers stay null, never 0."""
    run = load(ZMAI)
    attempt = run.cases[0].attempts[0]
    payload = json.loads(attempt_to_run_output(attempt))
    assert payload["input_tokens"] is None
    assert payload["output_tokens"] is None
    assert payload["input_tokens"] != 0
    assert payload["measurement_status"] == "unavailable"


def test_run_output_carries_subject_outcome_not_verdict() -> None:
    run = load(ZMAI)
    payload = json.loads(attempt_to_run_output(run.cases[0].attempts[0]))
    assert payload["subject_outcome"] == "COMPLETED"
    # Verdicts are produced by rules, never present on import.
    assert "verdict" not in payload


def test_run_output_signals_incomplete_trace() -> None:
    """trace_complete drives UNKNOWN vs FAIL, so it must be carried."""
    run = load(UNKNOWN_CASE)
    payload = json.loads(attempt_to_run_output(run.cases[0].attempts[0]))
    assert payload["trace_complete"] is False


# ------------------------------------------------------------------ plan
def test_plan_covers_all_cases_and_attempts() -> None:
    run = load(ZMWIKI)
    plan = plan_import(run)
    assert len(plan["examples"]) == len(run.cases)
    assert len(plan["runs"]) == sum(len(c.attempts) for c in run.cases)


def test_plan_reports_unsupported_fields_instead_of_dropping_silently() -> None:
    run = load(ZMAI)
    plan = plan_import(run)
    adapted = plan["coverage"]["adapted"]
    # The known gaps must be declared.
    assert any("snapshot_sha256" in a for a in adapted)
    assert any("verdict" in a for a in adapted)
    assert set(adapted) == set(UNSUPPORTED_FIELDS)


def test_plan_dataset_name_is_prefixed() -> None:
    run = load(ZMAI)
    assert plan_import(run)["dataset_name"].startswith("zmeval-")


# ------------------------------------------------------- semantic integrity
def test_mapping_does_not_mutate_the_source_run() -> None:
    run = load(ZMAI)
    before = run.content_sha256()
    plan_import(run)
    case_to_example(run.cases[0])
    run_to_experiment_metadata(run)
    assert run.content_sha256() == before


def test_no_field_is_invented() -> None:
    """Every experiment key is namespaced and traceable to the contract.

    ``content_sha256`` is a method on the run, not a field, so it is allowed
    explicitly rather than by a loose path check.
    """
    run = load(ZMAI)
    meta = run_to_experiment_metadata(run)
    dumped = run.model_dump(mode="json")
    allowed_derived = {"content_sha256"}
    for key in meta:
        assert key.startswith(NS)
        path = key[len(NS) :].split(".")
        assert path[0] in dumped or path[0] in allowed_derived, (
            f"{key} references unknown field {path[0]}"
        )


@pytest.mark.parametrize("path", [ZMAI, ZMWIKI, UNKNOWN_CASE], ids=lambda p: p.stem)
def test_plan_is_json_serializable(path: Path) -> None:
    """The plan must survive a real HTTP/JSON boundary unchanged."""
    plan = plan_import(load(path))
    roundtripped = json.loads(json.dumps(plan, ensure_ascii=False))
    assert roundtripped == plan
