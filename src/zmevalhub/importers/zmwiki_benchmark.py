"""Read-only adapter for ZMWiki Benchmark checkpoint JSONL."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from zmevalhub.schemas.v1 import (
    AttemptV1,
    CaseV1,
    EventV1,
    MeasurementStatus,
    SourceRunV1,
    SubjectOutcome,
)

IMPORTER_VERSION = "0.3.0"


class ZMWikiLogError(ValueError):
    """Malformed or internally contradictory ZMWiki source data."""


def _ids(value: object, label: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item
                                          for item in value):
        raise ZMWikiLogError(f"{label} must be a list of nonempty evidence IDs")
    return value


def _dataset_cases(path: Path | None) -> tuple[dict[str, dict], bytes | None]:
    if path is None:
        return {}, None
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZMWikiLogError(f"invalid dataset JSON: {exc}") from exc
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list):
        raise ZMWikiLogError("dataset must contain a cases array")
    indexed: dict[str, dict] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ZMWikiLogError("dataset case has no string id")
        if case["id"] in indexed:
            raise ZMWikiLogError(f"duplicate dataset case ID: {case['id']}")
        indexed[case["id"]] = case
    return indexed, raw


def adapt_zmwiki_file(
    path: str | Path, *, dataset_path: str | Path | None = None,
    arm: str | None = None, run_id: str | None = None,
) -> SourceRunV1:
    """Normalize raw rows without inventing an answer key or source snapshot."""
    source_path = Path(path)
    raw = source_path.read_bytes()
    dataset_file = Path(dataset_path) if dataset_path is not None else None
    reference_cases, dataset_bytes = _dataset_cases(dataset_file)
    source_hash = hashlib.sha256(raw).hexdigest()
    dataset_hash = hashlib.sha256(dataset_bytes).hexdigest() if dataset_bytes else None
    lines = [(number, line) for number, line in enumerate(raw.splitlines(), 1) if line.strip()]
    if not lines:
        raise ZMWikiLogError("benchmark JSONL has no results")
    if arm not in (None, "rag", "agent"):
        raise ZMWikiLogError("arm must be rag or agent")
    cases = []
    snapshot_hashes: set[str] = set()
    config_hashes: set[str] = set()
    for number, line in lines:
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ZMWikiLogError(f"invalid JSON at line {number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ZMWikiLogError(f"line {number} is not an object")
        nested = "rag" in record or "agent" in record
        if nested and arm is None:
            raise ZMWikiLogError("nested comparison JSONL requires --arm rag or agent")
        if not nested and arm is not None:
            raise ZMWikiLogError("--arm applies only to nested comparison JSONL")
        row = record.get(arm) if nested else record
        if not isinstance(row, dict):
            raise ZMWikiLogError(f"line {number} has no {arm} result")
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ZMWikiLogError(f"line {number} has no case ID")
        if nested and record.get("case_id") != case_id:
            raise ZMWikiLogError(f"line {number} outer/inner case IDs conflict")
        question = row.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ZMWikiLogError(f"line {number} has no question")
        base_ref = f"{source_path.resolve()}#line-{number}"
        reference = reference_cases.get(case_id)
        conflicts = []
        if dataset_file is not None and reference is None:
            conflicts.append("case absent from supplied dataset")
        if reference is not None:
            if reference.get("question") != question:
                conflicts.append("question differs from supplied dataset")
            if ("answerable" in reference and "answerable" in row
                    and reference["answerable"] != row["answerable"]):
                conflicts.append("answerable flag differs from supplied dataset")
            if (isinstance(row.get("reference_answer"), str)
                    and row["reference_answer"] != reference.get("reference_answer")):
                conflicts.append("reference answer differs from supplied dataset")
        row_gold = _ids(row.get("required_pages"), f"line {number} required_pages")
        dataset_gold = (_ids(reference.get("required_page_ids"),
                             f"dataset case {case_id} required_page_ids")
                        if reference is not None else None)
        if row_gold is not None and dataset_gold is not None and set(row_gold) != set(dataset_gold):
            conflicts.append("gold evidence IDs differ from supplied dataset")
        declared_hash = record.get("dataset_sha256") if nested else None
        if declared_hash is not None:
            if not isinstance(declared_hash, str) or len(declared_hash) != 64:
                raise ZMWikiLogError(f"line {number} has invalid dataset SHA-256")
            snapshot_hashes.add(declared_hash.lower())
            if dataset_hash is not None and declared_hash.lower() != dataset_hash:
                conflicts.append("dataset bytes differ from checkpoint SHA-256")
        config_hash = record.get("config_hash") if nested else None
        if config_hash is not None:
            if not isinstance(config_hash, str) or len(config_hash) != 64:
                raise ZMWikiLogError(f"line {number} has invalid config SHA-256")
            config_hashes.add(config_hash.lower())
        source_ids = _ids(row.get("sources"), f"line {number} sources")
        accessed_ids = _ids(row.get("accessed_pages"), f"line {number} accessed_pages")
        details = row.get("step_details")
        if details is not None and not isinstance(details, list):
            raise ZMWikiLogError(f"line {number} step_details must be a list")
        events = []
        for index, detail in enumerate(details or []):
            if not isinstance(detail, dict):
                raise ZMWikiLogError(f"line {number} step {index} is not an object")
            events.append(EventV1(sequence=index + 1, event_type="source_step",
                                  status="failed" if detail.get("error") else "ok",
                                  payload={"source_ref": f"{base_ref}#step-{index}",
                                           "action": detail.get("action"),
                                           "result_summary": detail.get("result_summary"),
                                           "read_page_ids": detail.get("read_page_ids"),
                                           "search_hit_page_ids": detail.get(
                                               "search_hit_page_ids")}))
        answer = row.get("answer")
        events.append(EventV1(sequence=len(events) + 1, event_type="answer",
                              status="ok" if row.get("status") == "answered" else "unknown",
                              payload={"source_ref": f"{base_ref}#answer",
                                       "answer": answer, "retrieved_evidence_ids": source_ids,
                                       "accessed_page_ids": accessed_ids,
                                       "reported_answer_correct": row.get("answer_correct"),
                                       "reported_evidence_recall": row.get("evidence_recall"),
                                       "reported_recall_numerator": row.get(
                                           "evidence_recall_numerator"),
                                       "reported_recall_denominator": row.get(
                                           "evidence_recall_denominator"),
                                       "source_status": row.get("status"),
                                       "source_error": row.get("error")}))
        outcome = (SubjectOutcome.COMPLETED if row.get("status") == "answered" and answer
                   else SubjectOutcome.FAILED if row.get("status") in {"error", "failed"}
                   else SubjectOutcome.UNKNOWN)
        prompt_tokens = row.get("prompt_tokens")
        completion_tokens = row.get("completion_tokens")
        measured = (type(prompt_tokens) is int and prompt_tokens >= 0
                    and type(completion_tokens) is int and completion_tokens >= 0)
        latency = row.get("latency_seconds")
        latency_ms = (round(latency * 1000) if isinstance(latency, (int, float))
                      and not isinstance(latency, bool) and math.isfinite(latency)
                      and latency >= 0 else None)
        reference_answer = (row.get("reference_answer")
                            if isinstance(row.get("reference_answer"), str)
                            else reference.get("reference_answer") if reference else None)
        expected = {"answerable": reference.get("answerable") if reference else row.get(
            "answerable"), "reference_answer": reference_answer,
                    "required_evidence_ids": row_gold,
                    "dataset_required_evidence_ids": dataset_gold,
                    "scoring_rule": row.get("scoring_rule"),
                    "reference_proven": (isinstance(row.get("reference_answer"), str)
                                         and bool(row["reference_answer"])
                                         or bool(reference is not None and declared_hash
                                                 and declared_hash.lower() == dataset_hash)),
                    "reference_source_ref": (f"{dataset_file.resolve()}#case-{case_id}"
                                             if reference is not None else None),
                    "reference_conflicts": conflicts}
        cases.append(CaseV1(case_id=case_id, kind="rag_agent",
                            input={"question": question}, expected=expected,
                            tags=[f"source:zmwiki-{arm or 'flat'}"],
                            attempts=[AttemptV1(attempt_index=0, subject_outcome=outcome,
                                                events=events, trace_complete=False,
                                                latency_ms=latency_ms,
                                                input_tokens=prompt_tokens if measured else None,
                                                output_tokens=(completion_tokens if measured
                                                               else None),
                                                measurement_status=(MeasurementStatus.MEASURED
                                                                    if measured else
                                                                    MeasurementStatus.UNAVAILABLE),
                                                error_type=(str(row["error"]) if row.get("error")
                                                            else None))]))
    if len(snapshot_hashes) > 1 or len(config_hashes) > 1:
        raise ZMWikiLogError("checkpoint rows declare conflicting run hashes")
    snapshot = next(iter(snapshot_hashes), None)
    return SourceRunV1(schema_version=1, source="zmwiki", source_run_id=run_id or
                       f"{source_path.stem}{('-' + arm) if arm else ''}",
                       source_sha256=source_hash, importer_version=IMPORTER_VERSION,
                       subject={"name": "ZMWiki", "config_sha256": next(iter(config_hashes),
                                                                        None)},
                       dataset={"name": dataset_file.stem if dataset_file else "zmwiki-benchmark",
                                "snapshot_sha256": snapshot if snapshot == dataset_hash else None},
                       cases=cases)
