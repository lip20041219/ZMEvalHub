import hashlib
import json

import pytest

from zmevalhub.importers.zmai_execution_log import ZmaiLogError, adapt_zmai_bytes
from zmevalhub.rules.agent_reliability import TraceSource, evaluate_agent_rules
from zmevalhub.schemas.v1 import SourceRunV1, Verdict


def log_bytes(steps):
    return json.dumps({
        "agent_id": "agent-7",
        "task": "Fix the test failure",
        "created_at": "2026-11-12T10:00:00Z",
        "step_count": len(steps),
        "steps": steps,
    }).encode()


def step(step_id, phase, action, **fields):
    return {"step_id": step_id, "phase": phase, "action": action,
            "success": True, "metadata": {}, **fields}


def test_real_format_converts_and_preserves_step_refs_scope_and_exit_code():
    raw = log_bytes([
        step(1, "fix_driving", "edit"),
        step(2, "tool_call", "shell_exec", tool_name="shell_exec",
             tool_input={"command": "pytest tests/test_rules.py -q"}),
        step(3, "tool_result", "shell_exec", tool_name="shell_exec",
             error="exit 1: 1 failed"),
        step(4, "finalize", "agent_finalize", metadata={"status": "completed"}),
    ])
    run = adapt_zmai_bytes(raw)
    SourceRunV1.model_validate_json(run.model_dump_json())
    case, = run.cases
    attempt, = case.attempts
    test_event = attempt.events[2]

    assert [event.sequence for event in attempt.events] == [1, 2, 3, 4]
    assert test_event.event_type == "test_run"
    assert test_event.payload["verification_scope"] == "target"
    assert test_event.exit_code == 1
    assert attempt.trace_complete is False
    results = evaluate_agent_rules(case, attempt)
    assert tuple(result.verdict for result in results) == (Verdict.UNKNOWN, Verdict.FAIL)
    assert "zmai://agent-7/step/3" in results[1].evidence_refs


def test_declared_step_count_conflict_is_rejected():
    log = json.loads(log_bytes([step(1, "init", "agent_initialize")]))
    log["step_count"] = 0
    with pytest.raises(ZmaiLogError, match="step_count"):
        adapt_zmai_bytes(json.dumps(log).encode())


def test_missing_source_steps_remain_unknown_not_error():
    raw = log_bytes([
        step(1, "tool_call", "shell_exec", tool_name="shell_exec",
             tool_input={"command": "pytest -q"}),
        step(2, "tool_result", "shell_exec", tool_name="shell_exec", error="exit 1: failed"),
        step(4, "finalize", "agent_finalize", metadata={"status": "completed"}),
    ])
    run = adapt_zmai_bytes(raw)
    case, = run.cases
    attempt, = case.attempts
    assert tuple(result.verdict for result in evaluate_agent_rules(case, attempt)) == (
        Verdict.UNKNOWN, Verdict.UNKNOWN
    )


def test_upstream_proof_conflict_returns_error_verdicts():
    run = adapt_zmai_bytes(log_bytes([
        step(1, "complete", "tests_passed", metadata={"reason": "exit=0"}),
        step(2, "finalize", "agent_finalize", metadata={"status": "completed"}),
    ]))
    case, = run.cases
    attempt, = case.attempts
    altered = attempt.events[0].model_copy(update={"status": "failed"})
    proof_bytes = (altered.model_dump_json() + "\n" +
                   attempt.events[1].model_dump_json() + "\n").encode()
    proof = TraceSource("upstream-trace.jsonl", proof_bytes,
                        hashlib.sha256(proof_bytes).hexdigest())

    assert tuple(result.verdict for result in evaluate_agent_rules(case, attempt, proof)) == (
        Verdict.ERROR, Verdict.ERROR
    )
