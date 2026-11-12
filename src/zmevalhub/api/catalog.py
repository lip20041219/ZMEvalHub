"""Whitelisted local evaluation artifacts; no request-supplied filesystem paths."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from zmevalhub.comparison import EvalBundle
from zmevalhub.importers.zmwiki_benchmark import adapt_zmwiki_file
from zmevalhub.paired_capture import load_run_capture
from zmevalhub.rules.agent_reliability import RuleResult, evaluate_all_agent_rules
from zmevalhub.rules.rag_deterministic import RagMetricResult, evaluate_rag_case
from zmevalhub.schemas.v1 import CaseKind, SourceRunV1

ArtifactType = Literal["source_run", "eval_bundle", "capture", "raw_checkpoint"]
Provenance = Literal["real", "real_masked", "synthetic", "unknown"]
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class ArtifactLoadError(ValueError):
    """A whitelisted artifact exists but fails validation."""


@dataclass(frozen=True)
class ArtifactPath:
    id: str
    path: Path
    root: Path
    relative_ref: str
    type: ArtifactType


@dataclass(frozen=True)
class LoadedArtifact:
    id: str
    relative_ref: str
    artifact_type: ArtifactType
    provenance: Provenance
    run: SourceRunV1
    evaluations: tuple[RuleResult | RagMetricResult, ...]
    bundle: EvalBundle | None
    evaluation_issues: tuple[str, ...]

    @property
    def verdict_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.verdict.value for item in self.evaluations).items()))

    @property
    def evaluation_status(self) -> str:
        counts = self.verdict_counts
        if "ERROR" in counts:
            return "ERROR"
        if "FAIL" in counts:
            return "FAIL"
        if self.evaluation_issues or "UNKNOWN" in counts or not counts:
            return "UNKNOWN"
        if set(counts) == {"SKIPPED"}:
            return "SKIPPED"
        return "PASS"

    @property
    def case_kind(self) -> str:
        kinds = {case.kind.value for case in self.run.cases}
        return next(iter(kinds)) if len(kinds) == 1 else "mixed"


class ArtifactCatalog:
    def __init__(self, roots: list[str | Path]):
        self.roots = tuple(Path(root).resolve() for root in roots)
        if not self.roots:
            raise ValueError("at least one artifact root is required")

    def _candidates(self) -> list[ArtifactPath]:
        candidates: list[ArtifactPath] = []
        for root_index, root in enumerate(self.roots):
            if not root.is_dir():
                continue
            paths = sorted((*root.rglob("*.json"), *root.rglob("*.jsonl")))
            for path in paths:
                if path.name == "metadata.json":
                    kind: ArtifactType = "capture"
                elif path.name in {"snapshot.json", "source_execution_log.json"}:
                    continue
                elif path.name.endswith(".proof.json"):
                    continue
                elif path.name.endswith("checkpoint.jsonl"):
                    kind = "raw_checkpoint"
                elif path.suffix == ".json":
                    kind = "source_run"  # upgraded to EvalBundle after validation
                else:
                    continue
                relative = path.relative_to(root).as_posix()
                identity = f"{root_index}:{kind}:{relative}"
                artifact_id = hashlib.sha256(identity.encode()).hexdigest()[:20]
                candidates.append(ArtifactPath(artifact_id, path, root,
                                               f"root-{root_index}/{relative}", kind))
        return sorted(candidates, key=lambda item: item.id)

    def paths(self) -> list[ArtifactPath]:
        return self._candidates()

    def find(self, artifact_id: str) -> ArtifactPath | None:
        if len(artifact_id) != 20 or any(char not in "0123456789abcdef" for char in artifact_id):
            return None
        return next((item for item in self._candidates() if item.id == artifact_id), None)

    @staticmethod
    def _safe_read(path: Path, root: Path) -> bytes:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or path.is_symlink() or not resolved.is_file():
            raise ArtifactLoadError("artifact path escapes its allowed root")
        if resolved.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ArtifactLoadError("artifact exceeds the read-only size limit")
        return resolved.read_bytes()

    def load(self, item: ArtifactPath) -> LoadedArtifact:
        try:
            if item.type == "capture":
                for name in ("metadata.json", "snapshot.json", "events.jsonl",
                             "events.jsonl.proof.json", "source_execution_log.json"):
                    self._safe_read(item.path.parent / name, item.root)
                bundle = load_run_capture(item.path.parent)
                run = bundle.source_run
            elif item.type == "raw_checkpoint":
                self._safe_read(item.path, item.root)
                run = adapt_zmwiki_file(item.path)
                bundle = None
            else:
                raw = self._safe_read(item.path, item.root)
                try:
                    bundle = EvalBundle.model_validate_json(raw)
                except ValidationError:
                    bundle = None
                run = bundle.source_run if bundle else SourceRunV1.model_validate_json(raw)
        except (OSError, ValueError, ValidationError) as exc:
            raise ArtifactLoadError(f"artifact failed validation: {type(exc).__name__}") from exc
        evaluations: list[RuleResult | RagMetricResult] = []
        issues = []
        if bundle is not None:
            evaluations.extend(bundle.evaluations)
        else:
            for case in run.cases:
                if case.kind == CaseKind.CODING_AGENT:
                    for attempt in case.attempts:
                        evaluations.extend(evaluate_all_agent_rules(case, attempt))
                else:
                    try:
                        evaluations.extend(evaluate_rag_case(case))
                    except ValueError as exc:
                        issues.append(f"{case.case_id}: {exc}")
        tags = {tag for case in run.cases for tag in case.tags}
        path_parts = set(item.path.parts)
        if "synthetic" in path_parts or run.source.startswith("synthetic") or any(
                "synthetic" in tag for tag in tags):
            provenance: Provenance = "synthetic"
        elif item.path.name.startswith("real_masked") or any(
                "real-masked" in tag for tag in tags):
            provenance = "real_masked"
        elif "provenance:real" in tags:
            provenance = "real"
        else:
            provenance = "unknown"
        artifact_type = ("eval_bundle" if bundle is not None and item.type == "source_run"
                         else item.type)
        return LoadedArtifact(item.id, item.relative_ref, artifact_type, provenance,
                              run, tuple(evaluations), bundle, tuple(issues))
