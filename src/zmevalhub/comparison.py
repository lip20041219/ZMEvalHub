"""Offline paired comparison of versioned Agent rule results."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zmevalhub.rules.agent_reliability import RuleResult
from zmevalhub.schemas.v1 import RunStatus, SourceRunV1, Verdict

ALLOWED_DIFFERENCES = frozenset({"git_sha", "model_id", "config_sha256", "prompt_version"})


class ExecutionConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int | None
    repetitions: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    timeout_ms: int = Field(ge=1)
    tool_environment_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    evaluator_config_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    prompt_version: str = Field(min_length=1)


class EvalBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run: SourceRunV1
    evaluations: list[RuleResult] = Field(min_length=1)
    conditions: ExecutionConditions


class CaseChange(BaseModel):
    case_id: str
    attempt_index: int
    rule_id: str
    rule_version: str
    baseline_verdict: Verdict
    candidate_verdict: Verdict
    change: Literal["improved", "regressed", "unchanged", "indeterminate"]
    baseline_evidence_refs: tuple[str, ...]
    candidate_evidence_refs: tuple[str, ...]
    baseline_reason: str
    candidate_reason: str


class Comparison(BaseModel):
    comparable: bool
    reasons: list[str]
    baseline_run_id: str
    candidate_run_id: str
    matched_cases: int
    changes: list[CaseChange]
    counts: dict[str, int]
    observed_balance: Literal["improved", "regressed", "mixed", "unchanged"] | None


def _case_fingerprint(case: object) -> str:
    payload = {"kind": case.kind.value, "input": case.input,
               "expected": case.expected, "tags": case.tags}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _results(bundle: EvalBundle, reasons: list[str]) -> dict[tuple[str, int, str, str], RuleResult]:
    attempts = {case.case_id: {attempt.attempt_index for attempt in case.attempts}
                for case in bundle.source_run.cases}
    refs = {}
    for case in bundle.source_run.cases:
        for attempt in case.attempts:
            allowed = {f"{case.case_id}/attempt-{attempt.attempt_index}"}
            for event in attempt.events:
                source_ref = event.payload.get("source_ref")
                if isinstance(source_ref, str) and source_ref:
                    allowed.add(source_ref)
                    allowed.add(f"{source_ref.split('#', 1)[0]}/attempt-{attempt.attempt_index}")
                else:
                    allowed.add(f"{case.case_id}/attempt-{attempt.attempt_index}#event-{event.sequence}")
            refs[case.case_id, attempt.attempt_index] = allowed
    by_key = {}
    for item in bundle.evaluations:
        key = (item.case_id, item.attempt_index, item.rule_id, item.rule_version)
        if item.case_id not in attempts:
            reasons.append(f"evaluation references absent case: {item.case_id}")
        elif item.attempt_index not in attempts[item.case_id]:
            reasons.append(f"evaluation references absent attempt: {key}")
        if key in by_key:
            reasons.append(f"duplicate evaluation: {key}")
        if not item.evidence_refs:
            reasons.append(f"evaluation has no evidence reference: {key}")
        elif (item.case_id, item.attempt_index) in refs:
            invalid = sorted(set(item.evidence_refs) - refs[item.case_id, item.attempt_index])
            if invalid:
                reasons.append(f"evaluation references absent evidence: {key}: {invalid}")
        by_key[key] = item
        if not item.rule_version:
            reasons.append(f"evaluation has no rule version: {key}")
    expected = {f"ZM-R{number:03}" for number in range(1, 7)}
    for case_id, indexes in attempts.items():
        if len(indexes) != bundle.conditions.repetitions:
            reasons.append(f"attempt count differs from repetitions: {case_id}")
        for index in indexes:
            if {key[2] for key in by_key if key[:2] == (case_id, index)} != expected:
                reasons.append(f"six-rule coverage is incomplete: {case_id}/attempt-{index}")
    for rule_id in expected:
        if len({key[3] for key in by_key if key[2] == rule_id}) > 1:
            reasons.append(f"mixed versions within rule: {rule_id}")
    return by_key


def compare_bundles(
    baseline: EvalBundle, candidate: EvalBundle,
    *, allowed_differences: frozenset[str] = frozenset(),
) -> Comparison:
    """Only a fully matched, explicitly controlled pair can yield a balance."""
    unknown_allowances = allowed_differences - ALLOWED_DIFFERENCES
    if unknown_allowances:
        raise ValueError(f"unknown allowed differences: {sorted(unknown_allowances)}")
    left, right = baseline.source_run, candidate.source_run
    reasons: list[str] = []
    if left.run_status != RunStatus.SUCCEEDED or right.run_status != RunStatus.SUCCEEDED:
        reasons.append("both evaluation runs must have SUCCEEDED status")
    if left.dataset.name != right.dataset.name:
        reasons.append("dataset names differ")
    if not left.dataset.snapshot_sha256 or not right.dataset.snapshot_sha256:
        reasons.append("dataset snapshot hash is missing")
    elif left.dataset.snapshot_sha256.lower() != right.dataset.snapshot_sha256.lower():
        reasons.append("dataset snapshot hashes differ")
    if left.subject.name != right.subject.name:
        reasons.append("subject names differ")
    if not left.subject.model_id or not right.subject.model_id:
        reasons.append("subject model ID is missing")
    left_cases = {case.case_id: case for case in left.cases}
    right_cases = {case.case_id: case for case in right.cases}
    matched = sorted(left_cases.keys() & right_cases.keys())
    if left_cases.keys() != right_cases.keys():
        base_only = sorted(left_cases.keys() - right_cases.keys())
        candidate_only = sorted(right_cases.keys() - left_cases.keys())
        reasons.append(f"case ID sets differ: baseline_only={base_only}, "
                       f"candidate_only={candidate_only}")
    for case_id in matched:
        if _case_fingerprint(left_cases[case_id]) != _case_fingerprint(right_cases[case_id]):
            reasons.append(f"case content differs: {case_id}")
    for field in ("seed", "repetitions", "concurrency", "timeout_ms",
                  "tool_environment_sha256", "evaluator_config_sha256"):
        before = getattr(baseline.conditions, field)
        after = getattr(candidate.conditions, field)
        if before is None or after is None:
            reasons.append(f"execution condition missing: {field}")
            continue
        if before != after:
            reasons.append(f"execution condition differs: {field}")
    for field in ("git_sha", "model_id", "config_sha256"):
        differs = getattr(left.subject, field) != getattr(right.subject, field)
        if differs and field not in allowed_differences:
            reasons.append(f"subject difference not declared: {field}")
    if (baseline.conditions.prompt_version != candidate.conditions.prompt_version
            and "prompt_version" not in allowed_differences):
        reasons.append("subject difference not declared: prompt_version")
    left_results = _results(baseline, reasons)
    right_results = _results(candidate, reasons)
    if left_results.keys() != right_results.keys():
        reasons.append("case/rule/version result sets differ")
    if reasons:
        return Comparison(comparable=False, reasons=sorted(set(reasons)),
                          baseline_run_id=left.source_run_id,
                          candidate_run_id=right.source_run_id,
                          matched_cases=len(matched), changes=[], counts={},
                          observed_balance=None)

    changes = []
    counts = {name: 0 for name in ("improved", "regressed", "unchanged", "indeterminate")}
    for case_id, attempt_index, rule_id, version in sorted(left_results):
        key = (case_id, attempt_index, rule_id, version)
        before, after = left_results[key], right_results[key]
        if {before.verdict, after.verdict} <= {Verdict.PASS, Verdict.FAIL}:
            if before.verdict == after.verdict:
                change = "unchanged"
            else:
                change = "improved" if after.verdict == Verdict.PASS else "regressed"
        else:
            change = "indeterminate"
        counts[change] += 1
        changes.append(CaseChange(case_id=case_id, attempt_index=attempt_index,
                                  rule_id=rule_id, rule_version=version,
                                  baseline_verdict=before.verdict, candidate_verdict=after.verdict,
                                  change=change,
                                  baseline_evidence_refs=before.evidence_refs,
                                  candidate_evidence_refs=after.evidence_refs,
                                  baseline_reason=before.reason,
                                  candidate_reason=after.reason))
    balance = None
    if not counts["indeterminate"]:
        if counts["improved"] and counts["regressed"]:
            balance = "mixed"
        elif counts["improved"]:
            balance = "improved"
        elif counts["regressed"]:
            balance = "regressed"
        else:
            balance = "unchanged"
    return Comparison(comparable=True, reasons=[], baseline_run_id=left.source_run_id,
                      candidate_run_id=right.source_run_id, matched_cases=len(matched),
                      changes=changes, counts=counts, observed_balance=balance)
