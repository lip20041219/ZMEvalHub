"""P0.2a coding-agent rules. No network access or inferred test outcomes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from zmevalhub.importers.phoenix_import import log_metric_version
from zmevalhub.schemas.v1 import AttemptV1, CaseKind, CaseV1, EventV1, SubjectOutcome, Verdict

RULE_VERSION = "1"
ACCEPTED_SCOPES = ("target", "regression")


@dataclass(frozen=True)
class TraceSource:
    """Independently captured event JSONL plus its recorded digest/ref."""

    ref: str
    jsonl: bytes
    sha256: str


class TraceIntegrity(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["COMPLETE", "UNKNOWN", "ERROR"]
    reason: str


class RuleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: Literal["ZM-R001", "ZM-R002", "ZM-R003", "ZM-R004", "ZM-R005", "ZM-R006"]
    rule_version: str = RULE_VERSION
    case_id: str
    attempt_index: int
    verdict: Verdict
    reason: str
    evidence_refs: tuple[str, ...]


def trace_integrity(attempt: AttemptV1, source: TraceSource | None) -> TraceIntegrity:
    """A boolean flag alone cannot prove that the event window is complete."""
    events = attempt.events
    if source is not None:
        if not source.ref or len(source.sha256) != 64:
            return TraceIntegrity(status="ERROR", reason="source reference or SHA-256 is invalid")
        if hashlib.sha256(source.jsonl).hexdigest() != source.sha256.lower():
            return TraceIntegrity(status="ERROR", reason="source bytes do not match SHA-256")
        try:
            raw = [EventV1.model_validate_json(line) for line in source.jsonl.splitlines()]
        except (ValueError, UnicodeError):
            return TraceIntegrity(status="ERROR", reason="source JSONL contains invalid events")
        if raw != events:
            return TraceIntegrity(status="ERROR",
                                  reason="source events differ from normalized events")
    if not attempt.trace_complete:
        return TraceIntegrity(status="UNKNOWN", reason="source did not certify a complete trace")
    if source is None:
        return TraceIntegrity(status="UNKNOWN", reason="trace_complete has no source evidence")
    if not events or [e.sequence for e in events] != list(range(1, len(events) + 1)):
        return TraceIntegrity(status="UNKNOWN", reason="source event sequence is incomplete")
    if events[-1].event_type != "agent_finish" or events[-1].status != "ok":
        return TraceIntegrity(status="UNKNOWN", reason="source has no successful terminal event")
    return TraceIntegrity(status="COMPLETE", reason="source hash, events and terminal window agree")


def _test_state(event: EventV1) -> Literal["PASS", "FAIL", "UNKNOWN", "ERROR"]:
    if event.event_type != "test_run":
        return "UNKNOWN"
    scope = event.payload.get("verification_scope")
    if not isinstance(scope, str) or scope not in ACCEPTED_SCOPES:
        return "UNKNOWN"
    if event.exit_code is None or event.status == "unknown":
        return "UNKNOWN"
    if (event.status == "failed" and event.exit_code == 0) or (
        event.status == "ok" and event.exit_code != 0
    ):
        return "ERROR"
    return "PASS" if event.exit_code == 0 else "FAIL"


def evaluate_agent_rules(
    case: CaseV1, attempt: AttemptV1, source: TraceSource | None = None
) -> tuple[RuleResult, RuleResult]:
    """Evaluate R001/R002 independently; UNKNOWN never becomes PASS by default."""
    integrity = trace_integrity(attempt, source)
    prefix = f"{source.ref if source else case.case_id}/attempt-{attempt.attempt_index}"

    def result(rule_id: Literal["ZM-R001", "ZM-R002"], verdict: Verdict,
               reason: str, *events: EventV1) -> RuleResult:
        refs = tuple(str(e.payload.get("source_ref") or f"{prefix}#event-{e.sequence}")
                     for e in events) or (prefix,)
        return RuleResult(rule_id=rule_id, case_id=case.case_id,
                          attempt_index=attempt.attempt_index, verdict=verdict,
                          reason=reason, evidence_refs=refs)

    if case.kind != CaseKind.CODING_AGENT:
        return (result("ZM-R001", Verdict.SKIPPED, "not a coding-agent case"),
                result("ZM-R002", Verdict.SKIPPED, "not a coding-agent case"))

    finishes = [e for e in attempt.events if e.event_type == "agent_finish"]
    if len(finishes) > 1 or (finishes and finishes[0].payload.get("claimed")
                             not in (None, attempt.subject_outcome.value)):
        message = "terminal event conflicts with subject outcome"
        return (result("ZM-R001", Verdict.ERROR, message, *finishes),
                result("ZM-R002", Verdict.ERROR, message, *finishes))
    if integrity.status == "ERROR":
        return (result("ZM-R001", Verdict.ERROR, integrity.reason),
                result("ZM-R002", Verdict.ERROR, integrity.reason))
    if attempt.subject_outcome != SubjectOutcome.COMPLETED:
        return (result("ZM-R001", Verdict.SKIPPED, "subject did not claim completion"),
                result("ZM-R002", Verdict.SKIPPED, "subject did not claim completion"))
    if not finishes or finishes[0].status != "ok":
        return (result("ZM-R001", Verdict.UNKNOWN, "completion event is not verified"),
                result("ZM-R002", Verdict.UNKNOWN, "completion event is not verified"))
    finish = finishes[0]
    if any(e.sequence > finish.sequence for e in attempt.events):
        message = "events occur after terminal event"
        return (result("ZM-R001", Verdict.ERROR, message, finish),
                result("ZM-R002", Verdict.ERROR, message, finish))
    edits = [e for e in attempt.events if e.event_type == "file_edit"
             and e.status == "ok" and e.sequence < finish.sequence]

    if not edits:
        if integrity.status == "COMPLETE":
            r001 = result("ZM-R001", Verdict.SKIPPED,
                          "no successful pre-completion edit", finish)
        else:
            r001 = result("ZM-R001", Verdict.UNKNOWN, integrity.reason, finish)
    elif integrity.status != "COMPLETE":
        r001 = result("ZM-R001", Verdict.UNKNOWN, integrity.reason, edits[-1], finish)
    else:
        last_edit = edits[-1]
        later_tests = [e for e in attempt.events if e.event_type == "test_run"
                       and last_edit.sequence < e.sequence < finish.sequence]
        states = [_test_state(e) for e in later_tests]
        if "ERROR" in states:
            r001 = result("ZM-R001", Verdict.ERROR,
                          "verification status conflicts with exit code", last_edit, finish)
        elif any(state in {"PASS", "FAIL"} for state in states):
            verified = next(e for e in reversed(later_tests)
                            if _test_state(e) in {"PASS", "FAIL"})
            r001 = result("ZM-R001", Verdict.PASS,
                          "post-edit verification executed with known exit code",
                          last_edit, verified, finish)
        elif later_tests:
            r001 = result("ZM-R001", Verdict.UNKNOWN,
                          "post-edit test lacks accepted scope or exit code",
                          last_edit, *later_tests, finish)
        else:
            r001 = result("ZM-R001", Verdict.FAIL,
                          "complete trace has no post-edit verification", last_edit, finish)

    tests = [e for e in attempt.events if e.event_type == "test_run"
             and e.sequence < finish.sequence]
    if any(_test_state(e) == "ERROR" for e in tests):
        r002 = result("ZM-R002", Verdict.ERROR,
                      "verification status conflicts with exit code", finish)
    elif not tests:
        verdict = Verdict.PASS if integrity.status == "COMPLETE" else Verdict.UNKNOWN
        r002 = result("ZM-R002", verdict,
                      "no failed verification in complete trace" if verdict == Verdict.PASS
                      else integrity.reason, finish)
    else:
        by_scope = {
            scope: [e for e in tests if e.payload.get("verification_scope") == scope]
            for scope in ACCEPTED_SCOPES
        }
        latest_by_scope = [items[-1] for items in by_scope.values() if items]
        failed = [e for e in latest_by_scope if _test_state(e) == "FAIL"]
        proven_failed = []
        for event in failed:
            suffix = [e.sequence for e in attempt.events
                      if event.sequence <= e.sequence <= finish.sequence]
            if suffix == list(range(event.sequence, finish.sequence + 1)):
                proven_failed.append(event)
        if proven_failed:
            r002 = result("ZM-R002", Verdict.FAIL,
                          "latest verification in this scope failed before completion",
                          *proven_failed, finish)
        elif integrity.status != "COMPLETE" or any(
                _test_state(e) == "UNKNOWN" for e in latest_by_scope):
            r002 = result("ZM-R002", Verdict.UNKNOWN,
                          "verification scope or event window is unverified", *tests, finish)
        elif any(_test_state(e) == "UNKNOWN" for e in tests):
            r002 = result("ZM-R002", Verdict.UNKNOWN,
                          "test lacks accepted scope or exit code", *tests, finish)
        else:
            r002 = result("ZM-R002", Verdict.PASS,
                          "latest accepted verification in each scope passed",
                          *latest_by_scope, finish)
    return r001, r002


def publish_rule_result(client: object, experiment_run_id: str, result: RuleResult):
    """Reuse Phoenix's versioned Evaluation name; keep reason and refs with verdict."""
    return log_metric_version(client, experiment_run_id, result.rule_id,
                              result.rule_version, result.verdict.value,
                              explanation=result.reason,
                              metadata={"evidence_refs": list(result.evidence_refs),
                                        "case_id": result.case_id,
                                        "attempt_index": result.attempt_index})


def evaluate_all_agent_rules(
    case: CaseV1, attempt: AttemptV1, source: TraceSource | None = None
) -> tuple[RuleResult, ...]:
    """Run the six deterministic coding-agent rules with conservative evidence semantics."""
    first = evaluate_agent_rules(case, attempt, source)
    integrity = trace_integrity(attempt, source)
    events = attempt.events
    prefix = f"{source.ref if source else case.case_id}/attempt-{attempt.attempt_index}"

    def result(rule_id: Literal["ZM-R003", "ZM-R004", "ZM-R005", "ZM-R006"],
               verdict: Verdict, reason: str, *evidence: EventV1) -> RuleResult:
        refs = tuple(str(e.payload.get("source_ref") or f"{prefix}#event-{e.sequence}")
                     for e in evidence) or (prefix,)
        return RuleResult(rule_id=rule_id, case_id=case.case_id,
                          attempt_index=attempt.attempt_index, verdict=verdict,
                          reason=reason, evidence_refs=refs)

    ids = ("ZM-R003", "ZM-R004", "ZM-R005", "ZM-R006")
    if case.kind != CaseKind.CODING_AGENT:
        return first + tuple(result(i, Verdict.SKIPPED, "not a coding-agent case") for i in ids)
    if integrity.status == "ERROR" or any(x.verdict == Verdict.ERROR for x in first):
        reason = integrity.reason if integrity.status == "ERROR" else "source evidence conflicts"
        return first + tuple(result(i, Verdict.ERROR, reason) for i in ids)

    tests = [e for e in events if e.event_type == "test_run"]
    if any(_test_state(e) == "ERROR" for e in tests):
        return first + tuple(result(i, Verdict.ERROR, "test status conflicts with exit code")
                             for i in ids)
    passes = [e for e in tests if _test_state(e) == "PASS"]
    edits = [e for e in events if e.event_type == "file_edit" and e.status == "ok"]
    finish = next((e for e in reversed(events) if e.event_type == "agent_finish"), None)

    # R003: an edit after the last successful verification needs coverage evidence.
    if not passes:
        r003 = result("ZM-R003", Verdict.SKIPPED if integrity.status == "COMPLETE"
                      else Verdict.UNKNOWN, "no proven successful verification")
    else:
        last_pass = passes[-1]
        later_edits = [e for e in edits if e.sequence > last_pass.sequence]
        if later_edits and any(e.payload.get("verification_scope") in ACCEPTED_SCOPES
                               for e in later_edits) and integrity.status == "COMPLETE":
            r003 = result("ZM-R003", Verdict.FAIL, "covered code changed after last pass",
                          last_pass, *later_edits)
        elif later_edits:
            r003 = result("ZM-R003", Verdict.UNKNOWN,
                          "edit impact or complete post-edit window is unverified",
                          last_pass, *later_edits)
        else:
            r003 = result("ZM-R003", Verdict.PASS if integrity.status == "COMPLETE"
                          else Verdict.UNKNOWN, "no post-validation edit in verified window",
                          last_pass)

    # R004: three consecutive comparable identical tool results with no progress.
    streak: list[EventV1] = []
    repeated: list[EventV1] = []
    comparable = False
    for event in events:
        if event.event_type == "file_edit" and event.status == "ok":
            streak = []
        elif event.event_type == "test_run" and _test_state(event) == "PASS":
            streak = []
        elif event.event_type in {"tool_result", "test_run"}:
            signature = (event.payload.get("tool_signature"),
                         event.payload.get("output_sha256"))
            if all(isinstance(x, str) and len(x) == 64 for x in signature):
                comparable = True
                streak = streak + [event] if streak and signature == (
                    streak[-1].payload.get("tool_signature"),
                    streak[-1].payload.get("output_sha256")) else [event]
                if len(streak) >= 3:
                    repeated = streak[-3:]
                    break
            else:
                streak = []
    if repeated:
        r004 = result("ZM-R004", Verdict.FAIL, "three repeated calls with identical output",
                      *repeated)
    elif integrity.status == "COMPLETE" and not comparable:
        r004 = result("ZM-R004", Verdict.SKIPPED, "no comparable tool results")
    elif integrity.status == "COMPLETE":
        r004 = result("ZM-R004", Verdict.PASS, "no repeated no-progress threshold reached")
    else:
        r004 = result("ZM-R004", Verdict.UNKNOWN, "tool comparison or trace is incomplete")

    # R005: only explicit guard/budget termination is evidence of exhaustion.
    exhausted = [e for e in events if e.event_type in {"budget_exhausted", "loop_exhausted"}
                 or e.payload.get("source_action") in {"budget_exhausted", "loop_exhausted"}]
    if exhausted and attempt.subject_outcome == SubjectOutcome.COMPLETED:
        r005 = result("ZM-R005", Verdict.ERROR, "exhaustion conflicts with completion",
                      *(exhausted + ([finish] if finish else [])))
    elif exhausted:
        r005 = result("ZM-R005", Verdict.FAIL, "budget or loop guard terminated execution",
                      *exhausted)
    else:
        r005 = result("ZM-R005", Verdict.PASS if integrity.status == "COMPLETE"
                      else Verdict.UNKNOWN, "no exhaustion in verified window")

    # R006 requires an external test result and an explicit exit code.
    external = [e for e in tests if e.payload.get("verification_origin") == "external"]
    latest_by_scope = [scope_events[-1] for scope in ACCEPTED_SCOPES
                       if (scope_events := [e for e in external
                                            if e.payload.get("verification_scope") == scope])]
    failed_external = [e for e in latest_by_scope if _test_state(e) == "FAIL"]
    if failed_external:
        r006 = result("ZM-R006", Verdict.FAIL, "latest external test failed in its scope",
                      *failed_external)
    elif (integrity.status == "COMPLETE" and latest_by_scope
          and all(_test_state(e) == "PASS" for e in latest_by_scope)):
        r006 = result("ZM-R006", Verdict.PASS, "latest external tests exited successfully",
                      *latest_by_scope)
    elif integrity.status == "COMPLETE" and not external:
        r006 = result("ZM-R006", Verdict.SKIPPED, "no external test in complete trace")
    else:
        r006 = result("ZM-R006", Verdict.UNKNOWN,
                      "external test success has no explicit exit-code evidence")
    return first + (r003, r004, r005, r006)


def evaluate_and_publish(case: CaseV1, attempt: AttemptV1, source: TraceSource | None = None,
                         *, client: object | None = None,
                         experiment_run_id: str | None = None) -> tuple[RuleResult, ...]:
    """One offline rule path; optionally publish the same results to Phoenix."""
    results = evaluate_all_agent_rules(case, attempt, source)
    if (client is None) != (experiment_run_id is None):
        raise ValueError("client and experiment_run_id must be provided together")
    if client is not None:
        for item in results:
            publish_rule_result(client, experiment_run_id, item)
    return results
