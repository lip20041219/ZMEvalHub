import hashlib
from pathlib import Path

from zmevalhub.rules.agent_reliability import (
    TraceSource,
    evaluate_agent_rules,
    publish_rule_result,
    trace_integrity,
)
from zmevalhub.schemas.v1 import AttemptV1, CaseV1, EventV1, SourceRunV1, Verdict


def event(sequence, event_type, *, status="ok", exit_code=None, scope=None, claimed=None):
    payload = {}
    if scope is not None:
        payload["verification_scope"] = scope
    if claimed is not None:
        payload["claimed"] = claimed
    return EventV1(sequence=sequence, event_type=event_type, status=status,
                   exit_code=exit_code, payload=payload)


def sample(events, *, complete=True, outcome="COMPLETED", source=True):
    case = CaseV1(case_id="case-1", kind="coding_agent")
    attempt = AttemptV1(attempt_index=0, subject_outcome=outcome,
                        trace_complete=complete, events=events)
    raw = b"\n".join(e.model_dump_json().encode() for e in events) + b"\n"
    proof = TraceSource("source-trace.jsonl", raw, hashlib.sha256(raw).hexdigest())
    return case, attempt, proof if source else None


def verdicts(*args):
    return tuple(r.verdict for r in evaluate_agent_rules(*args))


def test_complete_post_edit_verification_is_deterministic():
    args = sample([event(1, "file_edit"),
                   event(2, "test_run", exit_code=0, scope="target"),
                   event(3, "agent_finish", claimed="COMPLETED")])
    first = evaluate_agent_rules(*args)
    assert verdicts(*args) == (Verdict.PASS, Verdict.PASS)
    assert first == evaluate_agent_rules(*args)
    assert all(r.rule_version == "1" and r.reason and r.evidence_refs for r in first)
    assert "#event-2" in first[0].evidence_refs[1]


def test_complete_edit_without_verification_fails_r001():
    args = sample([event(1, "file_edit"), event(2, "agent_finish")])
    assert verdicts(*args) == (Verdict.FAIL, Verdict.PASS)


def test_boolean_claim_without_source_cannot_prove_absence_or_success():
    args = sample([event(1, "file_edit"), event(2, "agent_finish")], source=False)
    assert trace_integrity(args[1], args[2]).status == "UNKNOWN"
    assert verdicts(*args) == (Verdict.UNKNOWN, Verdict.UNKNOWN)


def test_existing_masked_fixture_does_not_invent_source_proof():
    path = Path(__file__).parent.parent / "fixtures/zmai/real_masked_coding_agent_pass.json"
    run = SourceRunV1.model_validate_json(path.read_bytes())
    case = run.cases[0]
    assert verdicts(case, case.attempts[0]) == (Verdict.UNKNOWN, Verdict.UNKNOWN)


def test_incomplete_trace_keeps_explicit_failed_test():
    args = sample([event(5, "test_run", status="failed", exit_code=1, scope="target"),
                   event(6, "agent_finish")], complete=False)
    assert verdicts(*args) == (Verdict.UNKNOWN, Verdict.FAIL)


def test_gap_after_failed_test_makes_last_result_unknown():
    args = sample([event(5, "test_run", status="failed", exit_code=1, scope="target"),
                   event(7, "agent_finish")], complete=False)
    assert verdicts(*args) == (Verdict.UNKNOWN, Verdict.UNKNOWN)


def test_failed_target_is_not_cleared_by_other_scope_pass():
    args = sample([event(1, "file_edit"),
                   event(2, "test_run", status="failed", exit_code=1, scope="target"),
                   event(3, "test_run", exit_code=0, scope="regression"),
                   event(4, "agent_finish")])
    assert verdicts(*args) == (Verdict.PASS, Verdict.FAIL)


def test_newer_target_success_clears_previous_target_failure():
    args = sample([event(1, "file_edit"),
                   event(2, "test_run", status="failed", exit_code=1, scope="target"),
                   event(3, "test_run", exit_code=0, scope="target"),
                   event(4, "agent_finish")])
    assert verdicts(*args) == (Verdict.PASS, Verdict.PASS)


def test_missing_exit_code_or_scope_is_not_verification():
    args = sample([event(1, "file_edit"),
                   event(2, "test_run", scope="target"),
                   event(3, "agent_finish")])
    assert verdicts(*args) == (Verdict.UNKNOWN, Verdict.UNKNOWN)


def test_incomplete_without_edit_is_unknown_not_skipped():
    args = sample([event(1, "agent_finish")], complete=False)
    assert verdicts(*args) == (Verdict.UNKNOWN, Verdict.UNKNOWN)


def test_no_edit_in_complete_trace_is_not_r001_violation():
    args = sample([event(1, "agent_finish")])
    assert verdicts(*args) == (Verdict.SKIPPED, Verdict.PASS)


def test_conflicting_completion_state_is_error():
    args = sample([event(1, "agent_finish", claimed="FAILED")])
    assert verdicts(*args) == (Verdict.ERROR, Verdict.ERROR)


def test_source_hash_mismatch_is_error():
    case, attempt, proof = sample([event(1, "agent_finish")])
    bad = TraceSource(proof.ref, proof.jsonl, "0" * 64)
    assert verdicts(case, attempt, bad) == (Verdict.ERROR, Verdict.ERROR)


def test_non_coding_case_is_skipped():
    _, attempt, proof = sample([event(1, "agent_finish")])
    case = CaseV1(case_id="rag-1", kind="rag_agent")
    assert verdicts(case, attempt, proof) == (Verdict.SKIPPED, Verdict.SKIPPED)


def test_phoenix_evaluation_carries_version_reason_and_event_refs():
    class Experiments:
        def log_evaluation(self, **kwargs):
            self.sent = kwargs
            return {"id": "evaluation-1"}

    class Client:
        experiments = Experiments()

    result = evaluate_agent_rules(*sample([
        event(1, "file_edit"), event(2, "agent_finish")]))[0]
    assert publish_rule_result(Client(), "run-1", result) == {"id": "evaluation-1"}
    sent = Client.experiments.sent
    assert sent["name"] == "ZM-R001@1" and sent["label"] == "FAIL"
    assert sent["explanation"] == result.reason
    assert sent["metadata"]["evidence_refs"] == list(result.evidence_refs)
