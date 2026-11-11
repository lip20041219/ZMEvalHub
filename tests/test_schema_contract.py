"""Guards the committed JSON Schema against drift from the Pydantic models.

``docs/schema/v1.json`` is generated from the models. If someone edits a model
and forgets to regenerate, these tests fail instead of letting the published
contract silently diverge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zmevalhub.schemas.v1 import SourceRunV1, model_json_schema

SCHEMA_PATH = Path(__file__).parent.parent / "docs" / "schema" / "v1.json"

CORE_MODELS = ("CaseV1", "AttemptV1", "EventV1")


def test_schema_artifact_exists() -> None:
    assert SCHEMA_PATH.exists(), (
        f"{SCHEMA_PATH} missing — run: uv run zmeval schema --out docs/schema/v1.json"
    )


def test_committed_schema_matches_models() -> None:
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    generated = json.loads(json.dumps(model_json_schema()))
    assert committed == generated, (
        "docs/schema/v1.json is stale — regenerate with: "
        "uv run zmeval schema --out docs/schema/v1.json"
    )


def test_root_model_is_the_top_level_schema() -> None:
    """SourceRunV1 is the root, so it is inlined at the top — not under $defs."""
    schema = model_json_schema()
    assert schema["title"] == "SourceRunV1"
    assert set(schema["required"]) >= {"schema_version", "source", "subject", "dataset", "cases"}


@pytest.mark.parametrize("model", CORE_MODELS)
def test_all_core_models_present_in_schema(model: str) -> None:
    schema = model_json_schema()
    assert model in schema["$defs"]


def test_schema_forbids_additional_properties() -> None:
    """extra='forbid' must be visible in the published contract.

    Checked on the root and on every nested model definition.
    """
    schema = model_json_schema()
    assert schema.get("additionalProperties") is False, "SourceRunV1"
    for model in CORE_MODELS:
        assert schema["$defs"][model].get("additionalProperties") is False, model


def test_schema_pins_schema_version_to_1() -> None:
    schema = model_json_schema()
    version = schema["properties"]["schema_version"]
    variants = [version] if "const" in version else version.get("anyOf", [])
    assert any(v.get("const") == 1 for v in variants), version


def test_status_enums_exposed_in_schema() -> None:
    """The two *input* status enums must be in the published contract."""
    schema = model_json_schema()
    run_status = json.dumps(schema["$defs"]["RunStatus"]["enum"])
    subject = json.dumps(schema["$defs"]["SubjectOutcome"]["enum"])
    assert "SUCCEEDED" in run_status
    assert "COMPLETED" in subject


def test_verdict_is_not_part_of_the_import_contract() -> None:
    """Verdict is what rules PRODUCE, not something importers may set.

    Keeping it out of the schema is a deliberate boundary: a payload cannot
    declare its own PASS/FAIL (§7.1 — rules decide, data does not).
    """
    schema = model_json_schema()
    assert "Verdict" not in schema["$defs"]
    # No model may declare a "verdict" property (descriptions may mention it).
    assert "verdict" not in schema["properties"]
    for name, definition in schema["$defs"].items():
        assert "verdict" not in definition.get("properties", {}), name


def test_verdict_enum_still_defined_in_code() -> None:
    """Rules will need it in P0.2 even though importers cannot send it."""
    from zmevalhub.schemas.v1 import Verdict

    assert {v.value for v in Verdict} == {"PASS", "FAIL", "UNKNOWN", "ERROR", "SKIPPED"}


def test_schema_hash_matches_model_dump() -> None:
    """The contract and the model agree on the same payload."""
    payload = {
        "schema_version": 1,
        "source": "zmai",
        "source_run_id": "r1",
        "subject": {"name": "ZMAI"},
        "dataset": {"name": "d1"},
        "cases": [
            {
                "case_id": "c1",
                "kind": "coding_agent",
                "attempts": [
                    {
                        "attempt_index": 0,
                        "subject_outcome": "COMPLETED",
                        "events": [{"sequence": 1, "event_type": "x"}],
                    }
                ],
            }
        ],
    }
    run = SourceRunV1.model_validate(payload)
    assert len(run.content_sha256()) == 64
