"""Tests for the validation entry point and the zmeval CLI.

Covers: located error paths, non-zero exit codes, no fabricated success.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zmevalhub.cli.main import EXIT_INVALID, EXIT_OK, EXIT_USAGE, main
from zmevalhub.validation import validate_file, validate_payload

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "fixtures"


def _base() -> dict:
    return json.loads(
        (FIXTURES / "zmai" / "real_masked_coding_agent_pass.json").read_text(encoding="utf-8")
    )


# ------------------------------------------------------------------ success
@pytest.mark.parametrize(
    "path",
    [
        FIXTURES / "zmai" / "real_masked_coding_agent_pass.json",
        FIXTURES / "zmwiki" / "real_masked_rag_multihop.json",
        FIXTURES / "synthetic" / "synthetic_false_completion.json",
        FIXTURES / "synthetic" / "synthetic_unknown_evidence.json",
    ],
    ids=lambda p: p.stem,
)
def test_valid_files_pass(path: Path) -> None:
    result = validate_file(path)
    assert result.ok is True
    assert result.issues == []
    assert result.summary["content_sha256"]


# ------------------------------------------------------------------ failure
@pytest.mark.parametrize(
    "name,fragment",
    [
        ("duplicate_event_sequence.json", "events"),
        ("events_out_of_order.json", "events"),
        ("missing_case_id.json", "case_id"),
        ("wrong_type_latency.json", "latency_ms"),
        ("unknown_field_typo.json", "attemps"),
        ("bad_schema_version.json", "schema_version"),
        ("measured_without_tokens.json", "attempts[0]"),
        ("invalid_sha256.json", "snapshot_sha256"),
        ("duplicate_case_id.json", "cases"),
        ("empty_cases.json", "cases"),
    ],
)
def test_invalid_files_rejected_with_locatable_path(name: str, fragment: str) -> None:
    result = validate_file(FIXTURES / "invalid" / name)
    assert result.ok is False
    assert result.issues
    assert any(fragment in i.path for i in result.issues), [i.path for i in result.issues]


def test_malformed_json_reports_line_column() -> None:
    result = validate_file(FIXTURES / "invalid" / "malformed.json")
    assert result.ok is False
    assert "line" in result.issues[0].path
    assert result.issues[0].error_type == "json_decode_error"


def test_missing_file_is_reported() -> None:
    result = validate_file(FIXTURES / "invalid" / "does-not-exist.json")
    assert result.ok is False
    assert result.issues[0].error_type == "file_error"


# ------------------------------------------- no fabricated success/verdict
def test_invalid_payload_never_yields_a_summary() -> None:
    """A rejected payload must not come back with success-looking numbers."""
    data = _base()
    data["schema_version"] = 99
    result = validate_payload(data)
    assert result.ok is False
    assert result.summary == {}


def test_validation_output_contains_no_verdict_claim() -> None:
    """P0.0 has no rules, so validation must never assert PASS/FAIL."""
    result = validate_file(FIXTURES / "synthetic" / "synthetic_false_completion.json")
    rendered = result.render()
    for word in ("PASS", "FAIL"):
        assert word not in rendered


# ---------------------------------------------------------------------- CLI
def test_cli_returns_zero_on_valid(tmp_path: Path) -> None:
    assert (
        main(["validate", str(FIXTURES / "zmai" / "real_masked_coding_agent_pass.json")]) == EXIT_OK
    )


def test_cli_returns_nonzero_on_invalid() -> None:
    assert main(["validate", str(FIXTURES / "invalid" / "missing_case_id.json")]) == EXIT_INVALID


def test_cli_returns_usage_code_on_missing_file() -> None:
    assert main(["validate", str(FIXTURES / "nope.json")]) == EXIT_USAGE


def test_cli_schema_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "v1.json"
    assert main(["schema", "--out", str(out)]) == EXIT_OK
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["title"] == "SourceRunV1"
    assert "CaseV1" in json.dumps(schema["$defs"])
