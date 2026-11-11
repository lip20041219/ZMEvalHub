"""ZMEvalHub — AI Agent reliability evaluation hub.

P0.0 scope: the unified data contract and its validator. No database, no
queue, no judge, no web UI yet — see ``docs/DEVELOPMENT_STATUS.md``.
"""

from zmevalhub.schemas.v1 import (
    SCHEMA_VERSION,
    AttemptV1,
    CaseKind,
    CaseV1,
    EventV1,
    RunStatus,
    SourceRunV1,
    SubjectOutcome,
    Verdict,
    model_json_schema,
)

__version__ = "0.1.0.dev0"

__all__ = [
    "SCHEMA_VERSION",
    "AttemptV1",
    "CaseKind",
    "CaseV1",
    "EventV1",
    "RunStatus",
    "SourceRunV1",
    "SubjectOutcome",
    "Verdict",
    "__version__",
    "model_json_schema",
]
