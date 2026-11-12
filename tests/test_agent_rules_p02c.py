import hashlib

from zmevalhub.importers.zmai_execution_log import _scope
from zmevalhub.rules.agent_reliability import TraceSource, evaluate_all_agent_rules
from zmevalhub.schemas.v1 import AttemptV1, CaseV1, EventV1, Verdict


def event(n, kind, *, status="ok", code=None, **payload):
    return EventV1(sequence=n, event_type=kind, status=status,
                   exit_code=code, payload=payload)


def run(events, *, complete=True, outcome="COMPLETED", kind="coding_agent"):
    case = CaseV1(case_id="case", kind=kind)
    attempt = AttemptV1(attempt_index=0, subject_outcome=outcome,
                        trace_complete=complete, events=events)
    raw = ("\n".join(e.model_dump_json() for e in events) + "\n").encode()
    proof = TraceSource("upstream.jsonl", raw, hashlib.sha256(raw).hexdigest())
    return evaluate_all_agent_rules(case, attempt, proof)


def test_r003_post_validation_edit_and_r006_scope_failure():
    results = run([
        event(1, "test_run", code=0, verification_scope="target",
              verification_origin="external"),
        event(2, "file_edit", verification_scope="target"),
        event(3, "test_run", status="failed", code=1, verification_scope="regression",
              verification_origin="external"),
        event(4, "agent_finish", claimed="COMPLETED"),
    ])
    assert results[2].verdict == Verdict.FAIL
    assert results[5].verdict == Verdict.FAIL
    assert all(r.rule_version == "1" and r.reason and r.evidence_refs for r in results)
    assert results == run([
        event(1, "test_run", code=0, verification_scope="target",
              verification_origin="external"),
        event(2, "file_edit", verification_scope="target"),
        event(3, "test_run", status="failed", code=1, verification_scope="regression",
              verification_origin="external"),
        event(4, "agent_finish", claimed="COMPLETED"),
    ])


def test_r004_repeat_and_r005_exhaustion():
    repeated = [event(n, "tool_result", tool_signature="a" * 64,
                      output_sha256="b" * 64) for n in (1, 2, 3)]
    results = run(repeated + [event(4, "agent_finish", claimed="COMPLETED")])
    assert results[3].verdict == Verdict.FAIL
    exhausted = run([event(1, "budget_exhausted"),
                     event(2, "agent_finish", status="failed", claimed="FAILED")],
                    outcome="FAILED", complete=False)
    assert exhausted[4].verdict == Verdict.FAIL


def test_r006_external_pass_and_r003_unknown_impact():
    results = run([event(1, "test_run", code=0, verification_scope="target",
                         verification_origin="external"),
                   event(2, "file_edit"),
                   event(3, "agent_finish", claimed="COMPLETED")])
    assert results[2].verdict == Verdict.UNKNOWN
    assert results[5].verdict == Verdict.PASS


def test_unknown_error_and_skipped_paths():
    unknown = run([event(1, "test_run", verification_scope="target"),
                   event(2, "agent_finish", claimed="COMPLETED")], complete=False)
    assert unknown[2].verdict == Verdict.UNKNOWN
    assert unknown[5].verdict == Verdict.UNKNOWN
    conflict = run([event(1, "test_run", status="failed", code=0,
                          verification_scope="target"),
                    event(2, "agent_finish", claimed="COMPLETED")])
    assert conflict[1].verdict == Verdict.ERROR
    assert all(r.verdict == Verdict.ERROR for r in conflict[2:])
    skipped = run([event(1, "agent_finish", claimed="COMPLETED")], kind="rag_agent")
    assert all(r.verdict == Verdict.SKIPPED for r in skipped)


def test_real_scope_command_ignores_chained_file_read():
    assert _scope('python -m pytest -q --tb=no & type tests\\test_net_value.py') == "regression"
    assert _scope('pytest tests/test_net_value.py -q') == "target"
