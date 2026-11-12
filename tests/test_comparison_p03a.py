import json

from zmevalhub.cli.main import main
from zmevalhub.comparison import EvalBundle, compare_bundles
from zmevalhub.rules.agent_reliability import RuleResult
from zmevalhub.schemas.v1 import AttemptV1, CaseV1, SourceRunV1, Verdict


def bundle(run_id, verdicts, *, snapshot="a" * 64, model="model-a", prompt="p1"):
    case = CaseV1(case_id="case-1", kind="coding_agent", input={"task": "fix"},
                  expected={"tests": "pass"}, attempts=[
                      AttemptV1(attempt_index=0, subject_outcome="COMPLETED",
                                events=[{"sequence": i, "event_type": "fixture",
                                         "payload": {"source_ref": f"{run_id}#event-{i}"}}
                                        for i in range(1, 7)])])
    run = SourceRunV1(schema_version=1, source="synthetic", source_run_id=run_id,
                      subject={"name": "agent", "model_id": model},
                      dataset={"name": "fixed-set", "snapshot_sha256": snapshot},
                      cases=[case])
    results = [RuleResult(rule_id=f"ZM-R{i:03}", case_id="case-1", attempt_index=0,
                          verdict=Verdict(verdict), reason="synthetic fixture",
                          evidence_refs=(f"{run_id}#event-{i}",))
               for i, verdict in enumerate(verdicts, 1)]
    return EvalBundle(source_run=run, evaluations=results,
                      conditions={"seed": 7, "repetitions": 1, "concurrency": 1,
                                  "timeout_ms": 30000,
                                  "tool_environment_sha256": "b" * 64,
                                  "evaluator_config_sha256": "c" * 64,
                                  "prompt_version": prompt})


def test_paired_changes_preserve_unknown_and_evidence():
    before = bundle("base", ["FAIL", "PASS", "UNKNOWN", "PASS", "PASS", "SKIPPED"])
    after = bundle("new", ["PASS", "FAIL", "PASS", "PASS", "PASS", "SKIPPED"])
    result = compare_bundles(before, after)
    assert result.comparable and result.matched_cases == 1
    assert result.counts == {"improved": 1, "regressed": 1, "unchanged": 2,
                             "indeterminate": 2}
    assert result.observed_balance is None
    assert result.changes[0].baseline_evidence_refs == ("base#event-1",)
    assert result.changes[0].candidate_evidence_refs == ("new#event-1",)
    assert result.model_dump() == compare_bundles(before, after).model_dump()


def test_missing_snapshot_case_or_conditions_refuse_trusted_comparison():
    before = bundle("base", ["FAIL"] * 6)
    after = bundle("new", ["PASS"] * 6)
    after.source_run.dataset.snapshot_sha256 = None
    after.source_run.cases[0].expected["tests"] = "changed"
    after.conditions.seed = 9
    result = compare_bundles(before, after)
    assert not result.comparable and not result.changes
    assert result.observed_balance is None
    assert any("snapshot" in reason for reason in result.reasons)
    assert any("case content" in reason for reason in result.reasons)
    assert any("seed" in reason for reason in result.reasons)


def test_model_prompt_difference_requires_declaration_and_cli(tmp_path, capsys):
    before = bundle("base", ["FAIL"] * 6)
    after = bundle("new", ["PASS"] * 6, model="model-b", prompt="p2")
    assert not compare_bundles(before, after).comparable
    allowed = frozenset({"model_id", "prompt_version"})
    compared = compare_bundles(before, after, allowed_differences=allowed)
    assert compared.observed_balance == "improved"
    paths = [tmp_path / "base.json", tmp_path / "new.json"]
    for path, value in zip(paths, (before, after), strict=True):
        path.write_text(value.model_dump_json(), encoding="utf-8")
    assert main(["compare", *map(str, paths), "--allow-difference", "model_id",
                 "--allow-difference", "prompt_version"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["improved"] == 6


def test_rule_version_and_case_set_mismatch_are_not_comparable():
    before = bundle("base", ["FAIL"] * 6)
    after = bundle("new", ["PASS"] * 6)
    after.evaluations[0] = after.evaluations[0].model_copy(update={"rule_version": "2"})
    result = compare_bundles(before, after)
    assert not result.comparable
    assert "case/rule/version result sets differ" in result.reasons
    after = bundle("new", ["PASS"] * 6)
    after.source_run.cases[0].case_id = "different-case"
    result = compare_bundles(before, after)
    assert not result.comparable
    assert any("case ID sets differ" in reason for reason in result.reasons)


def test_absent_evidence_and_repetition_mismatch_are_rejected():
    before = bundle("base", ["FAIL"] * 6)
    after = bundle("new", ["PASS"] * 6)
    after.evaluations[0] = after.evaluations[0].model_copy(
        update={"evidence_refs": ("new#event-99",)})
    result = compare_bundles(before, after)
    assert not result.comparable
    assert any("absent evidence" in reason for reason in result.reasons)
    after = bundle("new", ["PASS"] * 6)
    after.conditions.repetitions = 2
    result = compare_bundles(before, after)
    assert not result.comparable
    assert any("attempt count differs" in reason for reason in result.reasons)
