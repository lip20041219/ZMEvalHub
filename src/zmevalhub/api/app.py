"""Minimal read-only FastAPI workbench over validated local artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Generic, TypeVar
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zmevalhub.api.catalog import (
    ArtifactCatalog,
    ArtifactLoadError,
    ArtifactPath,
    LoadedArtifact,
)
from zmevalhub.comparison import Comparison, compare_bundles
from zmevalhub.gate import GateDecision, GatePolicy, evaluate_gate
from zmevalhub.rules.agent_reliability import RuleResult
from zmevalhub.rules.rag_deterministic import RagMetricResult
from zmevalhub.schemas.v1 import EventV1, SourceRunV1

T = TypeVar("T")
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOTS = [REPO_ROOT / "fixtures" / name for name in ("zmai", "zmwiki", "synthetic")]
DEFAULT_ROOTS.append(REPO_ROOT / ".zmevalhub" / "acceptance")
DEFAULT_POLICY = REPO_ROOT / "config" / "gates" / "agent_regression_v1.json"


class ResponseMeta(BaseModel):
    provenance: str | None = None
    status: str | None = None
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
    request_id: str


class RunSummary(BaseModel):
    id: str
    source_run_id: str | None
    source: str | None
    case_kind: str
    case_count: int
    artifact_type: str
    artifact_ref: str
    provenance: str
    evaluation_status: str
    verdict_counts: dict[str, int]
    issues: list[str]


class RunDetail(BaseModel):
    summary: RunSummary
    source_run: SourceRunV1
    evaluations: list[RuleResult | RagMetricResult]


class EvidenceDetail(BaseModel):
    case_id: str
    attempt_index: int
    events: list[EventV1]
    evaluations: list[RuleResult | RagMetricResult]
    evidence_refs: list[str]


def _summary(item: LoadedArtifact) -> RunSummary:
    return RunSummary(id=item.id, source_run_id=item.run.source_run_id,
                      source=item.run.source, case_kind=item.case_kind,
                      case_count=len(item.run.cases), artifact_type=item.artifact_type,
                      artifact_ref=item.relative_ref, provenance=item.provenance,
                      evaluation_status=item.evaluation_status,
                      verdict_counts=item.verdict_counts,
                      issues=list(item.evaluation_issues))


def _invalid_summary(path: ArtifactPath) -> RunSummary:
    return RunSummary(id=path.id, source_run_id=None, source=None, case_kind="invalid",
                      case_count=0, artifact_type=path.type, artifact_ref=path.relative_ref,
                      provenance="unknown", evaluation_status="BLOCKED",
                      verdict_counts={}, issues=["artifact failed Schema or source validation"])


def _pair_provenance(left: LoadedArtifact, right: LoadedArtifact) -> str:
    return left.provenance if left.provenance == right.provenance else "mixed"


def create_app(*, artifact_roots: Sequence[str | Path] | None = None,
               policy_file: str | Path | None = None) -> FastAPI:
    """HTTP clients see opaque IDs; only the app owner may configure local roots."""
    catalog = ArtifactCatalog(list(artifact_roots) if artifact_roots is not None else DEFAULT_ROOTS)
    policy = GatePolicy.model_validate_json(Path(policy_file or DEFAULT_POLICY).read_bytes())
    policy_id = f"{policy.name}@{policy.version}"
    app = FastAPI(title="ZMEvalHub Read-Only API", version="0.4a")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": detail.get("code", "ZM_API_ERROR"),
                                               "message": detail.get("message", "request failed"),
                                               "details": detail.get("details", {})},
                                     "request_id": request.state.request_id})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"loc": list(item["loc"]), "type": item["type"], "msg": item["msg"]}
                   for item in exc.errors()]
        return JSONResponse(status_code=422,
                            content={"error": {"code": "ZM_API_VALIDATION_FAILED",
                                               "message": "invalid API request",
                                               "details": {"issues": details}},
                                     "request_id": request.state.request_id})

    def _loaded(run_id: str) -> LoadedArtifact:
        path = catalog.find(run_id)
        if path is None:
            raise HTTPException(status_code=404, detail={"code": "ZM_RUN_NOT_FOUND",
                                                         "message": "run ID not found"})
        try:
            return catalog.load(path)
        except ArtifactLoadError as exc:
            raise HTTPException(status_code=422, detail={"code": "ZM_ARTIFACT_INVALID",
                                                         "message": "artifact failed validation",
                                                         "details": {"reason": str(exc)}}) from exc

    def _comparison(left: LoadedArtifact, right: LoadedArtifact,
                    differences: list[str]) -> Comparison:
        if left.bundle is None or right.bundle is None:
            missing = [item.id for item in (left, right) if item.bundle is None]
            return Comparison(comparable=False,
                              reasons=["versioned EvalBundle and execution conditions missing: " +
                                       ", ".join(missing)],
                              baseline_run_id=left.run.source_run_id,
                              candidate_run_id=right.run.source_run_id,
                              matched_cases=0, changes=[], counts={}, observed_balance=None)
        try:
            return compare_bundles(left.bundle, right.bundle,
                                   allowed_differences=frozenset(differences))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "ZM_COMPARISON_INVALID",
                                                         "message": str(exc)}) from exc

    @app.get("/healthz", response_model=Envelope[dict[str, str]])
    def healthz(request: Request):
        return Envelope(data={"status": "ok"}, request_id=request.state.request_id)

    @app.get("/readyz", response_model=Envelope[dict[str, Any]])
    def readyz(request: Request):
        ready = any(root.is_dir() for root in catalog.roots)
        available = sum(root.is_dir() for root in catalog.roots)
        return Envelope(data={"status": "ready" if ready else "unavailable",
                              "artifact_roots_available": available,
                              "policy_id": policy_id, "phoenix": "external_not_checked"},
                        meta=ResponseMeta(status="PASS" if ready else "BLOCKED"),
                        request_id=request.state.request_id)

    @app.get("/api/v1/runs", response_model=Envelope[list[RunSummary]])
    def list_runs(request: Request, limit: int = Query(20, ge=1, le=100),
                  offset: int = Query(0, ge=0)):
        summaries = []
        for path in catalog.paths():
            try:
                summaries.append(_summary(catalog.load(path)))
            except ArtifactLoadError:
                summaries.append(_invalid_summary(path))
        summaries.sort(key=lambda item: (item.source_run_id or "", item.id))
        return Envelope(data=summaries[offset:offset + limit],
                        meta=ResponseMeta(total=len(summaries), limit=limit, offset=offset),
                        request_id=request.state.request_id)

    @app.get("/api/v1/runs/{run_id}", response_model=Envelope[RunDetail])
    def get_run(run_id: str, request: Request):
        item = _loaded(run_id)
        return Envelope(data=RunDetail(summary=_summary(item), source_run=item.run,
                                       evaluations=list(item.evaluations)),
                        meta=ResponseMeta(provenance=item.provenance,
                                          status=item.evaluation_status),
                        request_id=request.state.request_id)

    @app.get("/api/v1/runs/{run_id}/evaluations",
             response_model=Envelope[list[RuleResult | RagMetricResult]])
    def get_evaluations(run_id: str, request: Request):
        item = _loaded(run_id)
        return Envelope(data=list(item.evaluations),
                        meta=ResponseMeta(provenance=item.provenance,
                                          status=item.evaluation_status,
                                          total=len(item.evaluations)),
                        request_id=request.state.request_id)

    @app.get("/api/v1/runs/{run_id}/evidence", response_model=Envelope[EvidenceDetail])
    def get_evidence(run_id: str, request: Request, case_id: str,
                     attempt_index: int = Query(0, ge=0)):
        item = _loaded(run_id)
        case = next((case for case in item.run.cases if case.case_id == case_id), None)
        attempt = (next((attempt for attempt in case.attempts
                         if attempt.attempt_index == attempt_index), None)
                   if case is not None else None)
        if attempt is None:
            raise HTTPException(status_code=404, detail={"code": "ZM_ATTEMPT_NOT_FOUND",
                                                         "message": "case or attempt not found"})
        evaluations = [result for result in item.evaluations
                       if result.case_id == case_id and result.attempt_index == attempt_index]
        refs = sorted({ref for result in evaluations for ref in result.evidence_refs})
        data = EvidenceDetail(case_id=case_id, attempt_index=attempt_index,
                              events=attempt.events, evaluations=evaluations,
                              evidence_refs=refs)
        return Envelope(data=data, meta=ResponseMeta(provenance=item.provenance,
                                                     status=item.evaluation_status),
                        request_id=request.state.request_id)

    @app.get("/api/v1/comparisons", response_model=Envelope[Comparison])
    def get_comparison(request: Request, baseline_id: str, candidate_id: str,
                       allow_difference: Annotated[list[str] | None, Query()] = None):
        left, right = _loaded(baseline_id), _loaded(candidate_id)
        result = _comparison(left, right, allow_difference or [])
        return Envelope(data=result,
                        meta=ResponseMeta(provenance=_pair_provenance(left, right),
                                          status="COMPARABLE" if result.comparable else "BLOCKED"),
                        request_id=request.state.request_id)

    @app.get("/api/v1/gates", response_model=Envelope[GateDecision])
    def get_gate(request: Request, baseline_id: str, candidate_id: str,
                 policy_id_query: Annotated[str | None, Query(alias="policy_id")] = None,
                 allow_difference: Annotated[list[str] | None, Query()] = None):
        if policy_id_query not in (None, policy_id):
            raise HTTPException(status_code=404, detail={"code": "ZM_POLICY_NOT_FOUND",
                                                         "message": "policy ID not found"})
        left, right = _loaded(baseline_id), _loaded(candidate_id)
        decision = evaluate_gate(_comparison(left, right, allow_difference or []), policy)
        return Envelope(data=decision,
                        meta=ResponseMeta(provenance=_pair_provenance(left, right),
                                          status=decision.status),
                        request_id=request.state.request_id)

    return app


app = create_app()
