"""Deterministic ZMWiki RAG checks; no LLM or semantic scoring."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from zmevalhub.importers.phoenix_import import log_metric_version
from zmevalhub.schemas.v1 import CaseKind, CaseV1, SourceRunV1, Verdict

METRIC_VERSION = "1"
EVALUATOR_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class RagMetricResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_id: Literal["evidence_recall", "evidence_missing", "answer_match"]
    metric_version: str = METRIC_VERSION
    case_id: str
    attempt_index: int
    verdict: Verdict
    value: float | None
    numerator: int | None
    denominator: int | None
    reason: str
    evidence_refs: tuple[str, ...]
    origin: Literal["deterministic_id_set", "upstream_zmwiki_assertion"]
    unit: Literal["ratio", "boolean"]
    direction: Literal["higher_is_better", "lower_is_better"]
    sample_count: int
    evaluator_hash: str


def _valid_ids(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def evaluate_rag_case(case: CaseV1) -> tuple[RagMetricResult, ...]:
    if case.kind != CaseKind.RAG_AGENT or len(case.attempts) != 1:
        raise ValueError("deterministic RAG evaluation requires one rag_agent attempt")
    attempt = case.attempts[0]
    answers = [event for event in attempt.events if event.event_type == "answer"]
    if len(answers) != 1:
        raise ValueError(f"case {case.case_id} needs one source answer event")
    event = answers[0]
    ref = event.payload.get("source_ref")
    if not isinstance(ref, str) or not ref:
        raise ValueError(f"case {case.case_id} has no answer source reference")
    dataset_ref = case.expected.get("reference_source_ref")
    refs = (ref, dataset_ref) if isinstance(dataset_ref, str) and dataset_ref else (ref,)

    def result(metric_id, verdict, reason, *, value=None, numerator=None,
               denominator=None, origin="deterministic_id_set"):
        return RagMetricResult(metric_id=metric_id, case_id=case.case_id,
                               attempt_index=attempt.attempt_index, verdict=verdict,
                               value=value, numerator=numerator, denominator=denominator,
                               reason=reason, evidence_refs=refs, origin=origin,
                               unit="ratio" if metric_id == "evidence_recall" else "boolean",
                               direction="lower_is_better" if metric_id == "evidence_missing"
                               else "higher_is_better", sample_count=1 if value is not None else 0,
                               evaluator_hash=EVALUATOR_HASH)

    conflicts = case.expected.get("reference_conflicts")
    if conflicts:
        reason = "reference conflict: " + "; ".join(str(item) for item in conflicts)
        return tuple(result(metric, Verdict.ERROR, reason,
                            origin="upstream_zmwiki_assertion" if metric == "answer_match"
                            else "deterministic_id_set")
                     for metric in ("evidence_recall", "evidence_missing", "answer_match"))

    gold = case.expected.get("required_evidence_ids")
    retrieved = event.payload.get("retrieved_evidence_ids")
    if gold is None or gold == []:
        evidence = [result(metric, Verdict.UNKNOWN, "gold evidence IDs are missing")
                    for metric in ("evidence_recall", "evidence_missing")]
    elif retrieved is None:
        evidence = [result(metric, Verdict.UNKNOWN, "retrieved evidence IDs are missing")
                    for metric in ("evidence_recall", "evidence_missing")]
    elif not _valid_ids(gold) or not _valid_ids(retrieved):
        evidence = [result(metric, Verdict.ERROR, "evidence IDs have an invalid shape")
                    for metric in ("evidence_recall", "evidence_missing")]
    else:
        gold_set, retrieved_set = set(gold), set(retrieved)
        missing = sorted(gold_set - retrieved_set)
        numerator, denominator = len(gold_set & retrieved_set), len(gold_set)
        value = numerator / denominator
        reported = event.payload.get("reported_evidence_recall")
        reported_num = event.payload.get("reported_recall_numerator")
        reported_den = event.payload.get("reported_recall_denominator")
        mismatch = ((reported is not None and
                     (not isinstance(reported, (int, float)) or isinstance(reported, bool)
                      or not math.isfinite(reported) or not math.isclose(reported, value,
                                                                         abs_tol=1e-9)))
                    or (reported_num is not None and reported_num != numerator)
                    or (reported_den is not None and reported_den != denominator))
        if mismatch:
            evidence = [result(metric, Verdict.ERROR,
                               "reported recall conflicts with source evidence IDs")
                        for metric in ("evidence_recall", "evidence_missing")]
        else:
            verdict = Verdict.PASS if not missing else Verdict.FAIL
            evidence = [result("evidence_recall", verdict,
                               f"{numerator}/{denominator} gold evidence IDs retrieved",
                               value=value, numerator=numerator, denominator=denominator),
                        result("evidence_missing", verdict,
                               "missing gold evidence IDs: " + ", ".join(missing)
                               if missing else "all gold evidence IDs present",
                               value=1.0 if missing else 0.0,
                               numerator=len(missing), denominator=denominator)]

    reference_answer = case.expected.get("reference_answer")
    reported_correct = event.payload.get("reported_answer_correct")
    answer = event.payload.get("answer")
    source_status = event.payload.get("source_status")
    if source_status == "answered" and (not isinstance(answer, str) or not answer.strip()):
        answer_match = result("answer_match", Verdict.ERROR,
                              "source claims answered but answer text is missing",
                              origin="upstream_zmwiki_assertion")
    elif reported_correct is True and source_status != "answered":
        answer_match = result("answer_match", Verdict.ERROR,
                              "reported correct answer conflicts with source status",
                              origin="upstream_zmwiki_assertion")
    elif not isinstance(reference_answer, str) or not reference_answer.strip():
        answer_match = result("answer_match", Verdict.UNKNOWN,
                              "reference answer is missing", origin="upstream_zmwiki_assertion")
    elif not case.expected.get("reference_proven"):
        answer_match = result("answer_match", Verdict.UNKNOWN,
                              "reference answer is not bound to this historical run",
                              origin="upstream_zmwiki_assertion")
    elif not isinstance(case.expected.get("answerable"), bool):
        answer_match = result("answer_match", Verdict.UNKNOWN,
                              "answerable label is missing", origin="upstream_zmwiki_assertion")
    elif case.expected.get("scoring_rule") != "keyword_group_match":
        answer_match = result("answer_match", Verdict.UNKNOWN,
                              "source scoring rule is missing or unsupported",
                              origin="upstream_zmwiki_assertion")
    elif not isinstance(reported_correct, bool):
        answer_match = result("answer_match", Verdict.UNKNOWN,
                              "ZMWiki answer correctness assertion is missing",
                              origin="upstream_zmwiki_assertion")
    else:
        answer_match = result("answer_match", Verdict.PASS if reported_correct else Verdict.FAIL,
                              "ZMWiki-reported deterministic answer_correct; not independently "
                              "rescored", value=1.0 if reported_correct else 0.0,
                              origin="upstream_zmwiki_assertion")
    return (*evidence, answer_match)


def evaluate_rag_run(run: SourceRunV1) -> tuple[RagMetricResult, ...]:
    return tuple(result for case in run.cases for result in evaluate_rag_case(case))


def publish_rag_results(client: object, results: tuple[RagMetricResult, ...],
                        run_ids: dict[str, str]) -> None:
    cases = {result.case_id for result in results}
    if set(run_ids) != cases or any(not isinstance(value, str) or not value
                                    for value in run_ids.values()):
        raise ValueError("Phoenix run-ID map must cover every case exactly")
    for result in results:
        log_metric_version(client, run_ids[result.case_id], result.metric_id,
                           result.metric_version, result.verdict.value,
                           explanation=result.reason,
                           metadata={"case_id": result.case_id,
                                     "attempt_index": result.attempt_index,
                                     "value": result.value,
                                     "numerator": result.numerator,
                                     "denominator": result.denominator,
                                     "origin": result.origin,
                                     "unit": result.unit,
                                     "direction": result.direction,
                                     "sample_count": result.sample_count,
                                     "evaluator_hash": result.evaluator_hash,
                                     "evidence_refs": list(result.evidence_refs)})
