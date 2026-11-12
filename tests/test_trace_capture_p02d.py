import json
from pathlib import Path

import pytest

from zmevalhub.cli.main import main
from zmevalhub.rules.agent_reliability import evaluate_and_publish, trace_integrity
from zmevalhub.rules.trace_capture import TraceCapture, load_capture
from zmevalhub.schemas.v1 import AttemptV1, CaseV1, EventV1, SourceRunV1, Verdict


def event(n, kind, *, status="ok", code=None, **payload):
    return EventV1(sequence=n, event_type=kind, status=status,
                   exit_code=code, payload=payload)


def captured(tmp_path, events):
    path = tmp_path / "events.jsonl"
    with TraceCapture(path, "synthetic-run-1") as collector:
        for item in events:
            collector.record(item)
        proof_path = collector.seal()
    source_events, source = load_capture(path, proof_path)
    attempt = AttemptV1(attempt_index=0, subject_outcome="COMPLETED",
                        trace_complete=True, events=source_events)
    return path, proof_path, CaseV1(case_id="synthetic-case", kind="coding_agent"), attempt, source


def test_new_capture_pass_and_phoenix_payload(tmp_path):
    _, _, case, attempt, source = captured(tmp_path, [
        event(1, "file_edit"),
        event(2, "test_run", code=0, verification_scope="target",
              verification_origin="external"),
        event(3, "agent_finish", claimed="COMPLETED"),
    ])

    class Experiments:
        def __init__(self):
            self.calls = []

        def log_evaluation(self, **kwargs):
            self.calls.append(kwargs)

    class Client:
        experiments = Experiments()

    results = evaluate_and_publish(case, attempt, source, client=Client(),
                                   experiment_run_id="phoenix-run-1")
    assert trace_integrity(attempt, source).status == "COMPLETE"
    assert [r.verdict for r in results] == [Verdict.PASS, Verdict.PASS, Verdict.PASS,
                                            Verdict.SKIPPED, Verdict.PASS, Verdict.PASS]
    assert len(Client.experiments.calls) == 6
    assert Client.experiments.calls[5]["name"] == "ZM-R006@1"
    assert Client.experiments.calls[5]["metadata"]["evidence_refs"] == [
        "capture:synthetic-run-1#event-2"]


def test_new_capture_fail_unknown_and_tamper(tmp_path):
    path, proof, case, attempt, source = captured(tmp_path, [
        event(1, "file_edit"), event(2, "agent_finish", claimed="COMPLETED")])
    assert evaluate_and_publish(case, attempt, source)[0].verdict == Verdict.FAIL
    path.write_bytes(path.read_bytes().replace(b"file_edit", b"tool_call"))
    with pytest.raises(ValueError, match="digest"):
        load_capture(path, proof)

    other = tmp_path / "other"
    other.mkdir()
    _, _, case, attempt, source = captured(other, [
        event(1, "test_run", verification_scope="target",
              verification_origin="external"),
        event(2, "agent_finish", claimed="COMPLETED")])
    results = evaluate_and_publish(case, attempt, source)
    assert results[1].verdict == Verdict.UNKNOWN
    assert results[5].verdict == Verdict.UNKNOWN


def test_collector_rejects_gaps_and_conflicting_test_state(tmp_path):
    with TraceCapture(tmp_path / "events.jsonl", "synthetic-run-2") as collector:
        with pytest.raises(ValueError, match="contiguous"):
            collector.record(event(2, "file_edit"))
        with pytest.raises(ValueError, match="exit code"):
            collector.record(event(1, "test_run", status="ok", code=1))


def test_cli_uses_sealed_trace_and_history_remains_unknown(tmp_path, capsys):
    path, proof, *_ = captured(tmp_path, [
        event(1, "file_edit"),
        event(2, "test_run", code=0, verification_scope="target",
              verification_origin="external"),
        event(3, "agent_finish", claimed="COMPLETED"),
    ])
    assert main(["evaluate-trace", str(path), str(proof), "--case-id", "synthetic-case"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output["evaluations"]) == 6
    assert output["trace_integrity"]["status"] == "COMPLETE"
    assert main(["evaluate-trace", str(path), str(proof), "--case-id", "synthetic-case",
                 "--publish-run-id", ""]) == 3
    assert "non-empty" in capsys.readouterr().err

    fixture = Path(__file__).parent.parent / "fixtures/zmai/real_masked_coding_agent_pass.json"
    historical = SourceRunV1.model_validate_json(fixture.read_bytes())
    case = historical.cases[0]
    results = evaluate_and_publish(case, case.attempts[0])
    assert all(item.verdict != Verdict.PASS for item in results)
