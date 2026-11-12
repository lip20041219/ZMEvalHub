"""Start-bound metadata and read-only capture of new ZMAI Agent runs."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from zmevalhub.comparison import EvalBundle, ExecutionConditions
from zmevalhub.importers.zmai_execution_log import adapt_zmai_bytes
from zmevalhub.rules.agent_reliability import evaluate_all_agent_rules, trace_integrity
from zmevalhub.rules.trace_capture import TraceCapture, load_capture
from zmevalhub.schemas.v1 import (
    AttemptV1,
    CaseV1,
    EventV1,
    SourceRunV1,
    SubjectOutcome,
    SubjectRef,
)


class RunSpec(BaseModel):
    """Declared before the subject starts; one case per captured Agent run."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_run_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    case: CaseV1
    subject: SubjectRef
    conditions: ExecutionConditions

    @model_validator(mode="after")
    def _single_fresh_attempt(self):
        if self.case.attempts:
            raise ValueError("run-start case snapshot must not contain attempts")
        if not self.subject.model_id:
            raise ValueError("subject model_id is required at run start")
        if self.conditions.repetitions != 1:
            raise ValueError("one capture must declare repetitions=1")
        return self


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    started_at: datetime
    spec: RunSpec
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot_bytes(case: CaseV1) -> bytes:
    return case.model_dump_json().encode("utf-8") + b"\n"


class RunCapture:
    """Create metadata before any subject event and bind it into TraceCapture."""

    def __init__(self, directory: str | Path, spec: RunSpec):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        snapshot = _snapshot_bytes(spec.case)
        self.snapshot_path = self.directory / "snapshot.json"
        with self.snapshot_path.open("xb") as output:
            output.write(snapshot)
            output.flush()
            os.fsync(output.fileno())
        metadata = RunMetadata(schema_version=1, started_at=datetime.now(UTC),
                               spec=spec, snapshot_sha256=_sha256(snapshot))
        self.metadata_path = self.directory / "metadata.json"
        raw = metadata.model_dump_json().encode("utf-8") + b"\n"
        with self.metadata_path.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        self.trace = TraceCapture(self.directory / "events.jsonl", spec.source_id)
        self.trace.record(EventV1(sequence=1, event_type="run_start", status="ok",
                                  payload={"metadata_sha256": _sha256(raw),
                                           "snapshot_sha256": metadata.snapshot_sha256}))

    def record(self, event: EventV1) -> EventV1:
        return self.trace.record(event)

    def seal(self) -> Path:
        return self.trace.seal()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.trace.__exit__(*_)


def load_run_capture(directory: str | Path) -> EvalBundle:
    """Verify the start metadata, sealed events, and rules before comparison."""
    root = Path(directory)
    metadata_raw = (root / "metadata.json").read_bytes()
    metadata = RunMetadata.model_validate_json(metadata_raw)
    snapshot_raw = (root / "snapshot.json").read_bytes()
    if _sha256(snapshot_raw) != metadata.snapshot_sha256:
        raise ValueError("case snapshot bytes conflict with run-start metadata")
    if snapshot_raw != _snapshot_bytes(metadata.spec.case):
        raise ValueError("case snapshot differs from run-start case")
    events, source = load_capture(root / "events.jsonl", root / "events.jsonl.proof.json")
    if source.ref != f"capture:{metadata.spec.source_id}":
        raise ValueError("capture source differs from run-start source ID")
    start = events[0]
    if (start.event_type != "run_start" or start.status != "ok"
            or start.payload.get("metadata_sha256") != _sha256(metadata_raw)
            or start.payload.get("snapshot_sha256") != metadata.snapshot_sha256):
        raise ValueError("run-start event does not bind metadata and case snapshot")
    upstream_prefixes = set()
    for event in events[1:]:
        upstream = event.payload.get("upstream_ref")
        step_hash = event.payload.get("upstream_step_sha256")
        if (not isinstance(upstream, str) or not upstream.startswith("zmai://")
                or not upstream.endswith(f"/step/{event.sequence - 1}")
                or not isinstance(step_hash, str) or len(step_hash) != 64):
            raise ValueError("captured event lacks a valid ZMAI source step reference")
        upstream_prefixes.add(upstream.rsplit("/step/", 1)[0])
    if len(upstream_prefixes) != 1:
        raise ValueError("captured events refer to different ZMAI sources")
    terminal = events[-1]
    source_log = (root / "source_execution_log.json").read_bytes()
    if terminal.payload.get("source_log_sha256") != _sha256(source_log):
        raise ValueError("final ZMAI log bytes conflict with sealed terminal event")
    original = json.loads(source_log)
    steps = original.get("steps") if isinstance(original, dict) else None
    if not isinstance(steps, list) or len(steps) != len(events) - 1:
        raise ValueError("final ZMAI source step count differs from capture")
    normalized = adapt_zmai_bytes(source_log).cases[0].attempts[0].events
    for captured, source_event, step in zip(events[1:], normalized, steps, strict=True):
        payload = {**source_event.payload,
                   "upstream_ref": source_event.payload["source_ref"],
                   "upstream_step_sha256": _sha256(json.dumps(
                       step, sort_keys=True, ensure_ascii=False).encode())}
        payload["source_ref"] = captured.payload["source_ref"]
        if captured.event_type == "agent_finish":
            payload["source_log_sha256"] = _sha256(source_log)
        expected = source_event.model_copy(update={"sequence": source_event.sequence + 1,
                                                   "payload": payload})
        if captured != expected:
            raise ValueError("captured event differs from final ZMAI source step")
    claimed = terminal.payload.get("claimed")
    try:
        outcome = SubjectOutcome(claimed)
    except ValueError as exc:
        raise ValueError("terminal event has no valid subject outcome") from exc
    attempt = AttemptV1(attempt_index=0, subject_outcome=outcome, events=events,
                        trace_complete=terminal.status == "ok")
    integrity = trace_integrity(attempt, source)
    if integrity.status != "COMPLETE":
        raise ValueError(f"capture cannot support a trusted pair: {integrity.reason}")
    case = metadata.spec.case.model_copy(update={"attempts": [attempt]})
    run = SourceRunV1(schema_version=1, source="zmai-live-capture",
                      source_run_id=metadata.spec.source_run_id,
                      source_sha256=source.sha256, subject=metadata.spec.subject,
                      dataset={"name": metadata.spec.dataset_name,
                               "snapshot_sha256": metadata.snapshot_sha256},
                      cases=[case])
    results = evaluate_all_agent_rules(case, attempt, source)
    return EvalBundle(source_run=run, evaluations=list(results),
                      conditions=metadata.spec.conditions)


def watch_zmai_run(
    spec: RunSpec, directory: str | Path, log_path: str | Path,
    *, poll_seconds: float = 0.2, timeout_seconds: float = 3600,
    on_ready=None,
) -> Path:
    """Observe a fresh ZMAI JSON log as it is persisted; never replay old logs."""
    pattern = str(log_path)
    if glob.glob(pattern):
        raise ValueError("ZMAI log already exists; refuse historical replay")
    if poll_seconds <= 0 or timeout_seconds <= 0:
        raise ValueError("poll and timeout must be positive")
    deadline = time.monotonic() + timeout_seconds
    seen_steps: list[str] = []
    source_identity = None
    source_path = None
    with RunCapture(directory, spec) as capture:
        if glob.glob(pattern):
            raise ValueError("ZMAI log appeared before capture was ready")
        if on_ready is not None:
            on_ready()
        while time.monotonic() < deadline:
            matches = sorted(glob.glob(pattern))
            if len(matches) > 1:
                raise ValueError("multiple ZMAI logs match the capture path")
            if matches and source_path is None:
                source_path = Path(matches[0])
            if matches and Path(matches[0]) != source_path:
                raise ValueError("ZMAI capture switched to a different log")
            if source_path is None or not source_path.exists():
                time.sleep(poll_seconds)
                continue
            try:
                raw = source_path.read_bytes()
                document = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                time.sleep(poll_seconds)
                continue  # atomic replacement may be in progress
            if not isinstance(document, dict) or not isinstance(document.get("steps"), list):
                raise ValueError("ZMAI log has no steps array")
            identity = (document.get("agent_id"), document.get("created_at"))
            if not all(isinstance(value, str) and value for value in identity):
                raise ValueError("ZMAI log has no stable agent ID or creation time")
            if source_identity is not None and identity != source_identity:
                raise ValueError("ZMAI source identity changed during capture")
            source_identity = identity
            steps = document["steps"]
            hashes = [_sha256(json.dumps(step, sort_keys=True, ensure_ascii=False).encode())
                      for step in steps]
            if hashes[:len(seen_steps)] != seen_steps:
                raise ValueError("previously observed ZMAI steps changed")
            if len(steps) > len(seen_steps):
                normalized = adapt_zmai_bytes(raw).cases[0].attempts[0].events
                if [event.sequence for event in normalized] != list(range(1, len(steps) + 1)):
                    raise ValueError("ZMAI step IDs are not contiguous from 1")
                terminal_seen = normalized[-1].event_type == "agent_finish"
                if terminal_seen and document.get("step_count") != len(steps):
                    raise ValueError("terminal ZMAI log has an incomplete step count")
                for event in normalized[len(seen_steps):]:
                    payload = {**event.payload, "upstream_ref": event.payload["source_ref"],
                               "upstream_step_sha256": hashes[event.sequence - 1]}
                    payload.pop("source_ref")
                    if event.event_type == "agent_finish":
                        payload["source_log_sha256"] = _sha256(raw)
                    capture.record(event.model_copy(update={
                        "sequence": event.sequence + 1, "payload": payload}))
                seen_steps = hashes
                if terminal_seen:
                    with (capture.directory / "source_execution_log.json").open("xb") as output:
                        output.write(raw)
                        output.flush()
                        os.fsync(output.fileno())
                    return capture.seal()
            time.sleep(poll_seconds)
    raise TimeoutError("ZMAI run did not reach a terminal event before timeout")
