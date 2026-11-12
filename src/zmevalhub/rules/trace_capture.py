"""Small file-backed collector for new, independently observed EventV1 streams."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from zmevalhub.rules.agent_reliability import TraceSource
from zmevalhub.schemas.v1 import EventV1


class TraceCapture:
    """Append events as observed; seal a separate proof only after termination.

    The collector must run outside the subject process's control. The digest proves
    local byte consistency, not the truth of omitted events or collector identity.
    """

    def __init__(self, events_path: str | Path, source_id: str):
        if not source_id:
            raise ValueError("source_id is required")
        self.path = Path(events_path)
        self.proof_path = self.path.with_suffix(self.path.suffix + ".proof.json")
        self.ref = f"capture:{source_id}"
        self.digest = hashlib.sha256()
        self.count = 0
        self.terminal: EventV1 | None = None
        self.stream = self.path.open("xb")

    def record(self, event: EventV1) -> EventV1:
        if self.stream.closed or self.terminal is not None:
            raise ValueError("capture is sealed or already terminated")
        if event.sequence != self.count + 1:
            raise ValueError("events must be contiguous from sequence 1")
        if (event.event_type == "test_run" and event.exit_code is not None
                and event.status != "unknown"):
            if (event.status == "ok") != (event.exit_code == 0):
                raise ValueError("test status conflicts with exit code")
        ref = f"{self.ref}#event-{event.sequence}"
        if event.payload.get("source_ref") not in (None, ref):
            raise ValueError("event source reference conflicts with collector")
        captured = event.model_copy(update={"payload": {**event.payload, "source_ref": ref}})
        data = captured.model_dump_json().encode() + b"\n"
        self.stream.write(data)
        self.stream.flush()
        self.digest.update(data)
        self.count += 1
        if event.event_type == "agent_finish":
            self.terminal = captured
        return captured

    def seal(self) -> Path:
        if self.terminal is None:
            raise ValueError("terminal event is required before sealing")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        proof = {
            "ref": self.ref,
            "sha256": self.digest.hexdigest(),
            "event_count": self.count,
            "terminal_status": self.terminal.status,
            "terminal_sequence": self.terminal.sequence,
        }
        with self.proof_path.open("x", encoding="utf-8") as output:
            json.dump(proof, output, sort_keys=True)
        return self.proof_path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if not self.stream.closed:
            self.stream.close()


def load_capture(events_path: str | Path, proof_path: str | Path):
    """Verify a sealed collector artifact and return events plus P0.2a proof."""
    raw = Path(events_path).read_bytes()
    proof = json.loads(Path(proof_path).read_text(encoding="utf-8"))
    if not isinstance(proof, dict) or not proof.get("ref"):
        raise ValueError("capture proof has no source identity")
    if hashlib.sha256(raw).hexdigest() != proof.get("sha256"):
        raise ValueError("capture bytes conflict with recorded digest")
    events = [EventV1.model_validate_json(line) for line in raw.splitlines()]
    if (not events or len(events) != proof.get("event_count")
            or [e.sequence for e in events] != list(range(1, len(events) + 1))
            or events[-1].event_type != "agent_finish"
            or events[-1].sequence != proof.get("terminal_sequence")
            or events[-1].status != proof.get("terminal_status")):
        raise ValueError("capture event count, sequence, or terminal conflicts with proof")
    if any(e.payload.get("source_ref") != f"{proof['ref']}#event-{e.sequence}"
           for e in events):
        raise ValueError("capture event source reference conflicts with proof")
    return events, TraceSource(proof["ref"], raw, proof["sha256"])
