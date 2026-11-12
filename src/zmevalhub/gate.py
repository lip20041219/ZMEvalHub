"""Deterministic, offline quality gate for paired Agent evaluations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zmevalhub.comparison import CaseChange, Comparison, EvalBundle, compare_bundles
from zmevalhub.schemas.v1 import Verdict


class GatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    mode: Literal["paired"] = "paired"
    on_incomparable: Literal["BLOCKED"] = "BLOCKED"
    on_indeterminate: Literal["BLOCKED"] = "BLOCKED"


class GateDecision(BaseModel):
    status: Literal["PASS", "FAIL", "BLOCKED"]
    policy_name: str | None
    policy_version: str | None
    baseline_run_id: str | None
    candidate_run_id: str | None
    reasons: list[str]
    findings: list[CaseChange]
    checked_changes: list[CaseChange]


def evaluate_gate(comparison: Comparison, policy: GatePolicy) -> GateDecision:
    """Confirmed regression wins; uncertainty blocks only an otherwise passing pair."""
    common = {"policy_name": policy.name, "policy_version": policy.version,
              "baseline_run_id": comparison.baseline_run_id,
              "candidate_run_id": comparison.candidate_run_id,
              "checked_changes": comparison.changes if comparison.comparable else []}
    if not comparison.comparable:
        return GateDecision(status="BLOCKED", reasons=comparison.reasons,
                            findings=[], **common)
    regressions = [change for change in comparison.changes
                   if change.baseline_verdict == Verdict.PASS
                   and change.candidate_verdict == Verdict.FAIL]
    if regressions:
        return GateDecision(status="FAIL",
                            reasons=[f"{len(regressions)} confirmed PASS-to-FAIL regression(s)"],
                            findings=regressions, **common)
    uncertain = [change for change in comparison.changes
                 if change.change == "indeterminate"
                 and not (change.baseline_verdict == Verdict.SKIPPED
                          and change.candidate_verdict == Verdict.SKIPPED)]
    if uncertain:
        return GateDecision(status="BLOCKED",
                            reasons=[f"{len(uncertain)} comparison(s) lack a definite verdict"],
                            findings=uncertain, **common)
    applicable = [change for change in comparison.changes
                  if change.baseline_verdict != Verdict.SKIPPED]
    if not applicable:
        return GateDecision(status="BLOCKED", reasons=["no applicable paired rules"],
                            findings=[], **common)
    return GateDecision(status="PASS", reasons=["no confirmed regression or unresolved verdict"],
                        findings=[], **common)


def gate_bundles(
    baseline: EvalBundle, candidate: EvalBundle, policy: GatePolicy,
    *, allowed_differences: frozenset[str] = frozenset(),
) -> GateDecision:
    return evaluate_gate(compare_bundles(baseline, candidate,
                                         allowed_differences=allowed_differences), policy)
