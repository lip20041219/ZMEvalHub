import hashlib
import json
from pathlib import Path

import pytest

from zmevalhub.cli.main import main
from zmevalhub.importers.zmwiki_benchmark import ZMWikiLogError, adapt_zmwiki_file
from zmevalhub.rules.rag_deterministic import evaluate_rag_run, publish_rag_results
from zmevalhub.schemas.v1 import SourceRunV1, Verdict

REAL_MASKED = (Path(__file__).parent.parent /
               "fixtures/zmwiki/real_masked_phase09_checkpoint.jsonl")


def test_real_masked_checkpoint_recall_and_missing_reference_are_explicit(capsys):
    run = adapt_zmwiki_file(REAL_MASKED)
    SourceRunV1.model_validate_json(run.model_dump_json())
    results = evaluate_rag_run(run)
    assert run.dataset.snapshot_sha256 is None
    assert [item.value for item in results if item.metric_id == "evidence_recall"] == [1.0, 2 / 3]
    assert [item.verdict for item in results if item.metric_id == "answer_match"] == [
        Verdict.UNKNOWN, Verdict.UNKNOWN]
    assert "#line-2#answer" in results[3].evidence_refs[0]
    assert results == evaluate_rag_run(run)
    assert main(["evaluate-zmwiki", str(REAL_MASKED)]) == 0
    assert len(json.loads(capsys.readouterr().out)["evaluations"]) == 6


def test_nested_checkpoint_with_matching_dataset_reports_answer_assertion(tmp_path):
    dataset = {"cases": [{"id": "q1", "question": "Q?", "reference_answer": "Answer",
                          "answerable": True, "required_page_ids": ["a", "b"]}]}
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    row = {"id": "q1", "question": "Q?", "answer": "Answer", "answer_correct": True,
           "answerable": True, "scoring_rule": "keyword_group_match", "status": "answered",
           "sources": ["a", "b"], "required_pages": ["a", "b"], "step_details": []}
    source = tmp_path / "nested.jsonl"
    source.write_text(json.dumps({"case_id": "q1", "dataset_sha256": digest,
                                  "config_hash": "a" * 64, "agent": row, "rag": row}) + "\n",
                      encoding="utf-8")
    with pytest.raises(ZMWikiLogError, match="--arm"):
        adapt_zmwiki_file(source, dataset_path=dataset_path)
    run = adapt_zmwiki_file(source, dataset_path=dataset_path, arm="agent")
    assert run.dataset.snapshot_sha256 == digest
    results = evaluate_rag_run(run)
    assert [item.verdict for item in results] == [Verdict.PASS] * 3
    assert results[2].origin == "upstream_zmwiki_assertion"

    class Experiments:
        def __init__(self):
            self.calls = []

        def log_evaluation(self, **kwargs):
            self.calls.append(kwargs)

    class Client:
        experiments = Experiments()

    publish_rag_results(Client(), results, {"q1": "phoenix-run-1"})
    assert [item["name"] for item in Client.experiments.calls] == [
        "evidence_recall@1", "evidence_missing@1", "answer_match@1"]
    assert Client.experiments.calls[0]["metadata"]["numerator"] == 2


def test_missing_gold_sources_and_conflicting_report_do_not_score(tmp_path):
    row = {"id": "q1", "question": "Q?", "answer": "Answer", "answer_correct": True,
           "answerable": True, "scoring_rule": "keyword_group_match", "status": "answered",
           "reference_answer": "Answer", "step_details": []}
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    results = evaluate_rag_run(adapt_zmwiki_file(source))
    assert [item.verdict for item in results] == [Verdict.UNKNOWN, Verdict.UNKNOWN,
                                                  Verdict.PASS]
    row["required_pages"] = ["a", "b"]
    row["sources"] = []
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    results = evaluate_rag_run(adapt_zmwiki_file(source))
    assert results[0].value == 0 and results[0].verdict == Verdict.FAIL
    row["evidence_recall"] = 1.0
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    results = evaluate_rag_run(adapt_zmwiki_file(source))
    assert results[0].verdict == results[1].verdict == Verdict.ERROR
    row["answer"] = ""
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert evaluate_rag_run(adapt_zmwiki_file(source))[2].verdict == Verdict.ERROR
    with pytest.raises(ValueError, match="every case"):
        publish_rag_results(object(), results, {})


def test_dataset_gold_conflict_and_malformed_jsonl(tmp_path):
    row = json.loads(REAL_MASKED.read_text(encoding="utf-8").splitlines()[0])
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    dataset = {"cases": [{"id": row["id"], "question": row["question"],
                          "reference_answer": "Person B is Director of Engineering.",
                          "answerable": True, "required_page_ids": ["wrong"]}]}
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    results = evaluate_rag_run(adapt_zmwiki_file(source, dataset_path=dataset_path))
    assert all(item.verdict == Verdict.ERROR for item in results)
    source.write_text('{"id": "q1"}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ZMWikiLogError):
        adapt_zmwiki_file(source)
