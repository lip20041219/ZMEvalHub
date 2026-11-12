"""Read-only adapter for ZMAI's ``.state/execution_log.json`` format."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from zmevalhub.schemas.v1 import (
    AttemptV1,
    CaseKind,
    CaseV1,
    EventV1,
    RunStatus,
    SourceRunV1,
    SubjectOutcome,
)

_EXIT_CODE = re.compile(r"\bexit(?:\s+code)?\s*[:=]?\s*(-?\d+)\b", re.IGNORECASE)
_TEST_COMMAND = re.compile(r"(?:pytest|unittest|tox|nox)\b", re.IGNORECASE)
_TEST_PATH = re.compile(r"(?:^|\s)(tests?[/\\][^\s]+|[^\s]+_test\.py|test_[^\s]+\.py)")


class ZmaiLogError(ValueError):
    """The source log is malformed or internally contradictory."""


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _exit_code(text: str | None) -> int | None:
    if not text:
        return None
    match = _EXIT_CODE.search(text)
    return int(match.group(1)) if match else None


def _scope(command: str) -> str:
    # ponytail: only the test invocation determines scope; later shell commands do not.
    invocation = re.split(r"\s*(?:&&|\|\||[&|;])\s*", command, maxsplit=1)[0]
    return "target" if _TEST_PATH.search(invocation) else "regression"


def _status(success: object) -> str:
    return "ok" if success is True else "failed" if success is False else "unknown"


def adapt_zmai_bytes(data: bytes) -> SourceRunV1:
    """Convert one captured ZMAI log without claiming its Trace is complete."""
    try:
        log = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZmaiLogError(f"invalid execution_log.json: {exc}") from exc
    if not isinstance(log, dict) or not isinstance(log.get("steps"), list):
        raise ZmaiLogError("execution log must be an object containing a steps array")
    steps = log["steps"]
    declared_count = log.get("step_count")
    if type(declared_count) is not int or declared_count < 0:
        raise ZmaiLogError("step_count must be a non-negative integer")
    if declared_count < len(steps):
        raise ZmaiLogError("step_count is smaller than the number of source steps")

    agent_id = str(log.get("agent_id") or "unknown-agent")
    source_run_id = f"{agent_id}@{log.get('created_at') or 'unknown-time'}"
    pending_commands: dict[str, str] = {}
    events: list[EventV1] = []
    terminal_steps: list[dict] = []
    for step in steps:
        if not isinstance(step, dict) or type(step.get("step_id")) is not int:
            raise ZmaiLogError("each source step must have an integer step_id")
        step_id = step["step_id"]
        if events and step_id <= events[-1].sequence:
            raise ZmaiLogError("source step IDs must be unique and ordered")

        phase = str(step.get("phase") or "unknown")
        action = str(step.get("action") or "unknown")
        tool_name = str(step.get("tool_name") or "")
        tool_input = _dict(step.get("tool_input"))
        metadata = _dict(step.get("metadata"))
        event_type = "source_step"
        event_status = _status(step.get("success"))
        exit_code = None
        payload: dict[str, object] = {
            "source_step_id": step_id,
            "source_phase": phase,
            "source_action": action,
            "source_tool": tool_name or None,
            "source_ref": f"zmai://{quote(agent_id, safe='')}/step/{step_id}",
        }

        if phase == "tool_call":
            event_type = "tool_call"
            command = tool_input.get("command")
            if tool_name and isinstance(command, str):
                pending_commands[tool_name] = command
        elif phase == "tool_result" and tool_name:
            command = pending_commands.pop(tool_name, "")
            error = step.get("error") if isinstance(step.get("error"), str) else ""
            output = step.get("tool_output") if isinstance(step.get("tool_output"), str) else ""
            code = _exit_code(error)
            if code is None:
                code = _exit_code(output)
            is_test = bool(_TEST_COMMAND.search(command) or "[test summary]" in error
                           or "[test summary]" in output)
            event_type = ("file_edit" if action in {"edit", "write_file", "force_modify"}
                          else "test_run" if is_test else "tool_result")
            if command:
                payload["tool_signature"] = hashlib.sha256(command.encode()).hexdigest()
            payload["output_sha256"] = hashlib.sha256((output + error).encode()).hexdigest()
            if is_test:
                exit_code = code
                event_status = "unknown" if code is None else ("ok" if code == 0 else "failed")
                payload["verification_scope"] = _scope(command) if command else "regression"
                payload["verification_origin"] = "external"
        elif action in {"edit", "write_file", "force_modify"}:
            event_type = "file_edit"
        elif action == "tests_passed":
            event_type = "test_run"
            reason = metadata.get("reason")
            code = _exit_code(reason) if isinstance(reason, str) else None
            exit_code = code
            event_status = "unknown" if code is None else ("ok" if code == 0 else "failed")
            payload["verification_scope"] = "regression"
        elif action == "agent_finalize":
            event_type = "agent_finish"
            terminal_steps.append(step)
            final_status = str(metadata.get("status") or "").upper()
            claimed = {
                "COMPLETED": SubjectOutcome.COMPLETED,
                "FAILED": SubjectOutcome.FAILED,
            }.get(final_status, SubjectOutcome.UNKNOWN)
            payload["claimed"] = claimed.value
            event_status = "ok" if claimed == SubjectOutcome.COMPLETED else (
                "failed" if claimed == SubjectOutcome.FAILED else "unknown"
            )

        events.append(EventV1(
            sequence=step_id,
            event_type=event_type,
            status=event_status,
            exit_code=exit_code,
            payload=payload,
        ))

    if len(terminal_steps) > 1 or (terminal_steps and terminal_steps[0] is not steps[-1]):
        raise ZmaiLogError("agent_finalize must occur exactly once as the last source step")

    claimed = SubjectOutcome.UNKNOWN
    if terminal_steps:
        final_status = str(_dict(terminal_steps[0].get("metadata")).get("status") or "").upper()
        claimed = {
            "COMPLETED": SubjectOutcome.COMPLETED,
            "FAILED": SubjectOutcome.FAILED,
        }.get(final_status, SubjectOutcome.UNKNOWN)

    case = CaseV1(
        case_id=f"zmai-{quote(agent_id, safe='')}",
        kind=CaseKind.CODING_AGENT,
        input={
            **({"task": log["task"]} if isinstance(log.get("task"), str) else {}),
            "source_step_count": len(steps),
            "declared_step_count": declared_count,
        },
        attempts=[AttemptV1(
            attempt_index=0,
            subject_outcome=claimed,
            events=events,
            trace_complete=False,
        )],
    )
    return SourceRunV1(
        schema_version=1,
        source="zmai",
        source_run_id=source_run_id,
        source_sha256=hashlib.sha256(data).hexdigest(),
        importer_version="0.2.0",
        subject={"name": "ZMAI"},
        dataset={"name": "zmai-execution-log"},
        cases=[case],
        run_status=RunStatus.SUCCEEDED,
    )


def adapt_zmai_file(path: str | Path) -> SourceRunV1:
    """Read and convert a ZMAI log; the external file is never modified."""
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise ZmaiLogError(f"cannot read {source}: {exc}") from exc
    return adapt_zmai_bytes(data)
