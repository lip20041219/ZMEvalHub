"""Schema validation entry point — turns Pydantic errors into locatable reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from zmevalhub.schemas.v1 import SourceRunV1


@dataclass
class ValidationIssue:
    """One error, located by JSON path so the user can find the offending line."""

    path: str
    message: str
    error_type: str

    @classmethod
    def from_pydantic(cls, err: dict[str, Any]) -> ValidationIssue:
        loc = [str(p) for p in err.get("loc", ())]
        # Rendered as cases[0].attempts[1].events[3].sequence — greppable.
        path = ""
        for part in loc:
            path += f"[{part}]" if part.isdigit() else (f".{part}" if path else part)
        return cls(
            path=path or "<root>",
            message=err.get("msg", "invalid value"),
            error_type=err.get("type", "unknown"),
        )

    def render(self) -> str:
        return f"  {self.path}: {self.message} [{self.error_type}]"


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        if self.ok:
            s = self.summary
            return (
                f"VALID  source={s['source']}  cases={s['cases']}  "
                f"attempts={s['attempts']}  run_status={s['run_status']}\n"
                f"  content_sha256={s['content_sha256']}"
            )
        lines = [f"INVALID  {len(self.issues)} error(s):"]
        lines.extend(i.render() for i in self.issues)
        return "\n".join(lines)


def validate_payload(payload: Any) -> ValidationResult:
    """Validate an already-parsed JSON object against the v1 contract."""
    try:
        run = SourceRunV1.model_validate(payload)
    except ValidationError as exc:
        return ValidationResult(
            ok=False, issues=[ValidationIssue.from_pydantic(e) for e in exc.errors()]
        )

    attempts = sum(len(c.attempts) for c in run.cases)
    return ValidationResult(
        ok=True,
        summary={
            "source": run.source,
            "cases": len(run.cases),
            "attempts": attempts,
            "run_status": run.run_status.value,
            "content_sha256": run.content_sha256(),
        },
    )


def validate_file(path: Path) -> ValidationResult:
    """Read a JSON file and validate it. Malformed JSON is a located error too."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue(path=str(path), message=str(exc), error_type="file_error")],
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ValidationResult(
            ok=False,
            issues=[
                ValidationIssue(
                    path=f"line {exc.lineno} column {exc.colno}",
                    message=f"malformed JSON: {exc.msg}",
                    error_type="json_decode_error",
                )
            ],
        )
    return validate_payload(payload)
