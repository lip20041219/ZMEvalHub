"""Contract tests for the v1 schemas.

Focus: the contract must reject bad data at runtime, and the three status
notions must stay separate concepts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from zmevalhub.schemas.v1 import (
    AttemptV1,
    CaseKind,
    CaseV1,
    EventV1,
    RunStatus,
    SourceRunV1,
    SubjectOutcome,
    Verdict,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
VALID = [
    FIXTURES / "zmai" / "real_masked_coding_agent_pass.json",
    FIXTURES / "zmwiki" / "real_masked_rag_multihop.json",
    FIXTURES / "synthetic" / "synthetic_false_completion.json",
    FIXTURES / "synthetic" / "synthetic_unknown_evidence.json",
]


def _base() -> dict:
    return json.loads(VALID[0].read_text(encoding="utf-8"))


# ---------------------------------------------------------------- happy path
@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_fixtures_parse(path: Path) -> None:
    run = SourceRunV1.model_validate_json(path.read_text(encoding="utf-8"))
    assert run.schema_version == 1
    assert len(run.cases) >= 1


def test_both_case_kinds_supported() -> None:
    coding = SourceRunV1.model_validate(_base())
    assert coding.cases[0].kind is CaseKind.CODING_AGENT

    rag = SourceRunV1.model_validate_json(VALID[1].read_text(encoding="utf-8"))
    assert rag.cases[0].kind is CaseKind.RAG_AGENT


# --------------------------------------------------- three statuses separate
def test_status_enums_are_distinct_types() -> None:
    """run_status / subject_outcome / verdict must never be interchangeable.

    They may share a spelling (both RunStatus and SubjectOutcome have FAILED),
    but they are distinct Python types, so a value cannot drift across
    boundaries unnoticed.
    """
    assert RunStatus is not SubjectOutcome
    assert SubjectOutcome is not Verdict
    assert RunStatus is not Verdict
    # The value that means "not enough evidence" must exist on Verdict only.
    assert Verdict.UNKNOWN.value == "UNKNOWN"
    assert "UNKNOWN" in set(SubjectOutcome)


def test_run_status_and_subject_outcome_are_not_interchangeable() -> None:
    """A shared spelling must not become a shared type."""
    assert RunStatus.FAILED is not SubjectOutcome.FAILED
    assert RunStatus.FAILED.value == SubjectOutcome.FAILED.value
    assert not isinstance(RunStatus.FAILED, SubjectOutcome)


def test_unknown_is_not_fail_and_error_is_not_fail() -> None:
    """The blueprint's central semantic rule (§6.1)."""
    assert Verdict.UNKNOWN != Verdict.FAIL
    assert Verdict.ERROR != Verdict.FAIL
    assert Verdict.UNKNOWN.value == "UNKNOWN"


def test_run_succeeded_does_not_imply_subject_success() -> None:
    run = SourceRunV1.model_validate(_base())
    assert run.run_status is RunStatus.SUCCEEDED
    # subject_outcome is a claim, tracked independently
    assert run.cases[0].attempts[0].subject_outcome is SubjectOutcome.COMPLETED


# ------------------------------------------------------------ field rejects
def test_duplicate_event_sequence_rejected() -> None:
    data = _base()
    data["cases"][0]["attempts"][0]["events"][1]["sequence"] = 1
    with pytest.raises(ValidationError, match="duplicate event sequence"):
        SourceRunV1.model_validate(data)


def test_out_of_order_events_rejected() -> None:
    data = _base()
    ev = data["cases"][0]["attempts"][0]["events"]
    ev[1], ev[2] = ev[2], ev[1]
    with pytest.raises(ValidationError, match="ordered by ascending sequence"):
        SourceRunV1.model_validate(data)


def test_missing_case_id_rejected() -> None:
    data = _base()
    del data["cases"][0]["case_id"]
    with pytest.raises(ValidationError) as exc:
        SourceRunV1.model_validate(data)
    assert any(e["loc"] == ("cases", 0, "case_id") for e in exc.value.errors())


def test_wrong_type_rejected() -> None:
    data = _base()
    data["cases"][0]["attempts"][0]["latency_ms"] = "not-a-number"
    with pytest.raises(ValidationError):
        SourceRunV1.model_validate(data)


def test_unknown_field_rejected() -> None:
    """A typo must fail loudly rather than be silently dropped."""
    data = _base()
    data["cases"][0]["attemps"] = []
    with pytest.raises(ValidationError, match="Extra inputs"):
        SourceRunV1.model_validate(data)


def test_bad_schema_version_rejected() -> None:
    data = _base()
    data["schema_version"] = 2
    with pytest.raises(ValidationError):
        SourceRunV1.model_validate(data)


def test_duplicate_case_id_rejected() -> None:
    data = _base()
    data["cases"].append(copy.deepcopy(data["cases"][0]))
    with pytest.raises(ValidationError, match="duplicate case_id"):
        SourceRunV1.model_validate(data)


def test_empty_cases_rejected() -> None:
    data = _base()
    data["cases"] = []
    with pytest.raises(ValidationError):
        SourceRunV1.model_validate(data)


def test_invalid_sha256_rejected() -> None:
    """Placeholder hashes like 'demo-dataset-hash' are not acceptable (§6.4)."""
    data = _base()
    data["dataset"]["snapshot_sha256"] = "demo-dataset-hash"
    with pytest.raises(ValidationError, match="String should match pattern"):
        SourceRunV1.model_validate(data)


# --------------------------------------------- no phantom measurements
def test_missing_tokens_stay_none_not_zero() -> None:
    """A missing measurement must never be coerced to 0 (§6.4)."""
    run = SourceRunV1.model_validate(_base())
    attempt = run.cases[0].attempts[0]
    assert attempt.input_tokens is None
    assert attempt.output_tokens is None
    assert attempt.input_tokens != 0


def test_measured_requires_tokens() -> None:
    data = _base()
    a = data["cases"][0]["attempts"][0]
    a["measurement_status"] = "measured"
    a["input_tokens"] = None
    with pytest.raises(ValidationError, match="requires input_tokens"):
        SourceRunV1.model_validate(data)


# --------------------------------------------------- evidence completeness
def test_trace_complete_flag_roundtrips() -> None:
    """trace_complete drives UNKNOWN vs FAIL, so it must survive parsing."""
    run = SourceRunV1.model_validate_json(
        (FIXTURES / "synthetic" / "synthetic_unknown_evidence.json").read_text(encoding="utf-8")
    )
    assert run.cases[0].attempts[0].trace_complete is False


def test_default_trace_complete_is_false() -> None:
    """Safe default: an unannotated log is NOT assumed complete."""
    attempt = AttemptV1(attempt_index=0, subject_outcome=SubjectOutcome.COMPLETED)
    assert attempt.trace_complete is False


def test_no_verdict_field_exists_on_attempt() -> None:
    """Verdicts are produced by rules, never accepted from imported data."""
    assert "verdict" not in AttemptV1.model_fields
    assert "run_status" not in CaseV1.model_fields


# --------------------------------------------------------------- integrity
def test_content_sha256_is_stable_and_deterministic() -> None:
    a = SourceRunV1.model_validate(_base())
    b = SourceRunV1.model_validate(_base())
    assert a.content_sha256() == b.content_sha256()
    assert len(a.content_sha256()) == 64


def test_content_sha256_changes_with_payload() -> None:
    a = SourceRunV1.model_validate(_base())
    data = _base()
    data["cases"][0]["case_id"] = "different-case"
    b = SourceRunV1.model_validate(data)
    assert a.content_sha256() != b.content_sha256()


def test_content_sha256_ignores_importer_version() -> None:
    """Re-import with a newer importer must stay idempotent."""
    a = SourceRunV1.model_validate(_base())
    data = _base()
    data["importer_version"] = "9.9.9"
    b = SourceRunV1.model_validate(data)
    assert a.content_sha256() == b.content_sha256()


def test_event_time_order_enforced() -> None:
    with pytest.raises(ValidationError, match="time_end must not precede"):
        EventV1(
            sequence=1,
            event_type="test_run",
            time_start="2026-01-01T00:00:10Z",
            time_end="2026-01-01T00:00:05Z",
        )
