import json

from test_comparison_p03a import bundle

from zmevalhub.cli.main import main
from zmevalhub.gate import GatePolicy, gate_bundles
from zmevalhub.schemas.v1 import Verdict

POLICY = GatePolicy(schema_version=1, name="agent-regression", version="1")


def test_gate_pass_is_deterministic_and_skipped_pair_is_neutral():
    before = bundle("base", ["FAIL", "PASS", "PASS", "SKIPPED", "PASS", "PASS"])
    after = bundle("new", ["PASS", "PASS", "PASS", "SKIPPED", "PASS", "PASS"])
    decision = gate_bundles(before, after, POLICY)
    assert decision.status == "PASS" and decision.policy_version == "1"
    assert len(decision.checked_changes) == 6
    assert decision.checked_changes[0].candidate_evidence_refs == ("new#event-1",)
    assert decision.model_dump() == gate_bundles(before, after, POLICY).model_dump()


def test_confirmed_regression_fails_even_with_improvement_and_unknown():
    before = bundle("base", ["PASS", "FAIL", "PASS", "PASS", "PASS", "PASS"])
    after = bundle("new", ["FAIL", "PASS", "UNKNOWN", "PASS", "PASS", "PASS"])
    decision = gate_bundles(before, after, POLICY)
    assert decision.status == "FAIL" and len(decision.findings) == 1
    finding = decision.findings[0]
    assert (finding.case_id, finding.rule_id, finding.rule_version) == ("case-1", "ZM-R001", "1")
    assert finding.baseline_evidence_refs == ("base#event-1",)
    assert finding.candidate_evidence_refs == ("new#event-1",)
    assert len(decision.checked_changes) == 6


def test_uncertainty_and_incomparability_block():
    before = bundle("base", ["PASS"] * 6)
    for verdict in ("UNKNOWN", "ERROR"):
        after = bundle("new", [verdict] + ["PASS"] * 5)
        decision = gate_bundles(before, after, POLICY)
        assert decision.status == "BLOCKED"
        assert decision.findings[0].candidate_verdict.value == verdict
    after = bundle("new", ["PASS"] * 6)
    after.source_run.dataset.snapshot_sha256 = None
    decision = gate_bundles(before, after, POLICY)
    assert decision.status == "BLOCKED" and not decision.findings
    assert any("snapshot" in reason for reason in decision.reasons)
    before = bundle("base", ["SKIPPED"] * 6)
    after = bundle("new", ["SKIPPED"] * 6)
    assert gate_bundles(before, after, POLICY).status == "BLOCKED"


def test_cli_exit_codes_invalid_policy_and_declared_model_difference(tmp_path, capsys):
    before = bundle("base", ["PASS"] * 6)
    after = bundle("new", ["PASS"] * 6)
    paths = [tmp_path / name for name in ("base.json", "new.json", "policy.json")]
    for path, value in zip(paths[:2], (before, after), strict=True):
        path.write_text(value.model_dump_json(), encoding="utf-8")
    paths[2].write_text(POLICY.model_dump_json(), encoding="utf-8")
    command = ["gate", str(paths[0]), str(paths[1]), "--policy", str(paths[2])]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    after.evaluations[0] = after.evaluations[0].model_copy(update={"verdict": Verdict.FAIL})
    paths[1].write_text(after.model_dump_json(), encoding="utf-8")
    assert main(command) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
    after.source_run.subject.model_id = "new-model"
    paths[1].write_text(after.model_dump_json(), encoding="utf-8")
    assert main(command) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    assert main(command + ["--allow-difference", "model_id"]) == 1
    capsys.readouterr()
    paths[2].write_text('{"schema_version": 2, "name": "bad", "version": "1"}',
                        encoding="utf-8")
    assert main(command) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED" and "gate input invalid" in payload["reasons"][0]
