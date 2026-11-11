"""ZMEvalHub domain schemas — the unified evaluation data contract.

The single most important rule in this module: three different notions of
"success" exist and must never be conflated.

* ``RunStatus``      — did the *platform* finish evaluating?
* ``SubjectOutcome`` — what the *subject under test* claimed about itself?
* ``Verdict``        — what the *rules* determined, given evidence?

``UNKNOWN`` means "there is not enough verifiable evidence", and is NOT a
``FAIL``. ``ERROR`` means "the evaluator itself broke", and is NOT a subject
failure. Both distinctions are enforced in code, not in prompt text.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 1

# SHA-256 as 64 lowercase/uppercase hex chars. Blueprint §6.4 requires real,
# verifiable hashes — the illustrative "demo-dataset-hash" placeholder is not
# acceptable as production data.
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


# --------------------------------------------------------------------------
# The three orthogonal status enums
# --------------------------------------------------------------------------
class RunStatus(StrEnum):
    """Platform-side execution state of an evaluation run.

    ``SUCCEEDED`` means the evaluation work completed. It does NOT mean the
    subject under test passed.
    """

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELED = "CANCELED"


class SubjectOutcome(StrEnum):
    """What the subject under test reported about itself (§6.1).

    This is a *claim*, not a result. A subject may report ``COMPLETED`` while
    never having verified anything.
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class Verdict(StrEnum):
    """What the deterministic rules determined (§6.1).

    * ``PASS``    — evidence satisfies the rule.
    * ``FAIL``    — evidence affirmatively contradicts success.
    * ``UNKNOWN`` — insufficient or incomplete evidence. NOT a FAIL.
    * ``ERROR``   — the evaluator failed. NOT a subject failure.
    * ``SKIPPED`` — the rule did not apply to this case.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class CaseKind(StrEnum):
    """Which family of reliability rules applies to a case."""

    CODING_AGENT = "coding_agent"
    RAG_AGENT = "rag_agent"


class MeasurementStatus(StrEnum):
    """Whether a numeric measurement is actually available (§6.4).

    A missing token count must be ``null`` + ``UNAVAILABLE``, never ``0``.
    """

    MEASURED = "measured"
    UNAVAILABLE = "unavailable"


Sha256 = Annotated[str, Field(pattern=_SHA256_RE.pattern)]


class _StrictModel(BaseModel):
    """Reject unknown fields so typos surface instead of being silently kept."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False, str_strip_whitespace=True)


# --------------------------------------------------------------------------
# EventV1
# --------------------------------------------------------------------------
class EventV1(_StrictModel):
    """One observable event in a subject's execution trace.

    ``sequence`` is the monotonic ordering key. It is authoritative: ordering
    must survive logs that lack reliable wall-clock timestamps (§6.4).
    """

    sequence: int = Field(ge=1, description="Monotonic 1-based ordering key.")
    event_type: str = Field(min_length=1, description="Normalized event type, e.g. 'file_edit'.")
    status: Literal["ok", "failed", "unknown"] = Field(
        default="unknown",
        description="Outcome of the event itself. 'unknown' when the source log cannot tell.",
    )
    time_start: datetime | None = None
    time_end: datetime | None = None
    exit_code: int | None = Field(
        default=None, description="Process exit code for shell/verification events."
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Free-form event detail; treated as untrusted data."
    )

    @model_validator(mode="after")
    def _check_time_order(self) -> EventV1:
        if self.time_start and self.time_end and self.time_end < self.time_start:
            raise ValueError("time_end must not precede time_start")
        return self


# --------------------------------------------------------------------------
# AttemptV1
# --------------------------------------------------------------------------
class AttemptV1(_StrictModel):
    """One execution attempt for a single case.

    A case may be attempted several times; ``attempt_index`` keeps them apart
    instead of overwriting earlier results (§6.2).
    """

    attempt_index: int = Field(ge=0, description="0-based attempt ordinal within the case.")
    subject_outcome: SubjectOutcome = Field(
        description="What the subject CLAIMED. Never a verdict."
    )
    events: list[EventV1] = Field(default_factory=list)
    # ``None`` == not measured. Never coerce a missing measurement to 0.
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    cost_currency: str | None = None
    measurement_status: MeasurementStatus = Field(
        default=MeasurementStatus.UNAVAILABLE,
        description="'unavailable' forbids presenting missing numbers as real measurements.",
    )
    error_type: str | None = Field(
        default=None, description="Set when the SUBJECT errored (e.g. 'model_error')."
    )
    trace_complete: bool = Field(
        default=False,
        description=(
            "True only when the source log is known to be complete. Rules that need a "
            "full event window must return UNKNOWN when this is False (§7.2 ZM-R001)."
        ),
    )

    @field_validator("events")
    @classmethod
    def _check_sequences(cls, events: list[EventV1]) -> list[EventV1]:
        seqs = [e.sequence for e in events]
        if len(seqs) != len(set(seqs)):
            dupes = sorted({s for s in seqs if seqs.count(s) > 1})
            raise ValueError(f"duplicate event sequence numbers: {dupes}")
        if seqs != sorted(seqs):
            raise ValueError("events must be ordered by ascending sequence")
        return events

    @model_validator(mode="after")
    def _check_measurement_semantics(self) -> AttemptV1:
        if self.measurement_status is MeasurementStatus.MEASURED:
            if self.input_tokens is None or self.output_tokens is None:
                raise ValueError(
                    "measurement_status='measured' requires input_tokens and output_tokens"
                )
        return self


# --------------------------------------------------------------------------
# CaseV1
# --------------------------------------------------------------------------
class CaseV1(_StrictModel):
    """One evaluation case: an input, its expectation, and the attempts made."""

    case_id: str = Field(min_length=1, description="Stable id, mapped from the source run.")
    kind: CaseKind
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(
        default_factory=dict,
        description="What the case requires, e.g. {'requires_post_edit_test': true}.",
    )
    tags: list[str] = Field(default_factory=list)
    attempts: list[AttemptV1] = Field(default_factory=list)

    @field_validator("attempts")
    @classmethod
    def _check_attempt_indexes(cls, attempts: list[AttemptV1]) -> list[AttemptV1]:
        idx = [a.attempt_index for a in attempts]
        if len(idx) != len(set(idx)):
            raise ValueError("duplicate attempt_index within a case")
        return attempts


# --------------------------------------------------------------------------
# SourceRunV1 — the top-level import contract
# --------------------------------------------------------------------------
class SubjectRef(_StrictModel):
    """Identity of the thing under test (§6.4)."""

    name: str = Field(min_length=1)
    git_sha: str | None = Field(
        default=None,
        description="Commit under test. Optional: import-only subjects may have no git history.",
    )
    model_id: str | None = None
    config_sha256: Sha256 | None = None


class DatasetRef(_StrictModel):
    name: str = Field(min_length=1)
    snapshot_sha256: Sha256 | None = Field(
        default=None,
        description="Content hash of the evaluated dataset. Required before A/B comparison.",
    )


class SourceRunV1(_StrictModel):
    """A normalized external evaluation result (``schema_version = 1``).

    This is the boundary object produced by importers. Upstream projects are
    never modified; adapters only *convert* into this shape.
    """

    schema_version: Literal[1]
    source: str = Field(min_length=1, description="Adapter name, e.g. 'zmai' / 'zmwiki'.")
    source_run_id: str = Field(min_length=1)
    source_sha256: Sha256 | None = Field(
        default=None, description="Hash of the original import bytes, for idempotency."
    )
    importer_version: str = Field(default="0.1.0")
    subject: SubjectRef
    dataset: DatasetRef
    cases: list[CaseV1] = Field(min_length=1)
    run_status: RunStatus = Field(
        default=RunStatus.SUCCEEDED,
        description="Platform execution state only. Does not imply subject success.",
    )

    @field_validator("cases")
    @classmethod
    def _check_unique_case_ids(cls, cases: list[CaseV1]) -> list[CaseV1]:
        ids = [c.case_id for c in cases]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate case_id: {dupes}")
        return cases

    def content_sha256(self) -> str:
        """Canonical hash of the payload, excluding volatile bookkeeping fields.

        Used for idempotent re-import: the same content must not create a
        duplicate run (§6.3).
        """
        payload = self.model_dump(mode="json", exclude={"source_sha256", "importer_version"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def model_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for the contract, for ``schemas/v1.json``."""
    return SourceRunV1.model_json_schema()


__all__ = [
    "SCHEMA_VERSION",
    "AttemptV1",
    "CaseKind",
    "CaseV1",
    "DatasetRef",
    "EventV1",
    "MeasurementStatus",
    "RunStatus",
    "SourceRunV1",
    "SubjectOutcome",
    "SubjectRef",
    "Verdict",
    "model_json_schema",
]
