"""Probe: can OpenInference/OTel spans carry ZMEvalHub trace semantics?

Verifies that a ZMAI-shaped run (file_edit -> test_run -> agent_finish) can be
emitted as OpenInference spans and read back with attributes intact.
"""

from __future__ import annotations

import os

ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = ENDPOINT
os.environ["PHOENIX_PROJECT_NAME"] = "zmeval-trace-probe"

from openinference.semconv.trace import (  # noqa: E402
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from phoenix.otel import register  # noqa: E402

tracer_provider = register(project_name="zmeval-trace-probe", auto_instrument=False)
tracer = tracer_provider.get_tracer("zmevalhub")

EXIT_CODE = "exit_code"
VERIFIED = "zmeval.verified"


def report(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def emit_zmai_attempt(tracer):
    """Map a ZMAI attempt into OpenInference spans."""
    with tracer.start_as_current_span("zmai.attempt.case-1") as run_span:
        run_span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.AGENT.value
        )
        run_span.set_attribute(SpanAttributes.INPUT_VALUE, "fix failing test")
        run_span.set_attribute(
            SpanAttributes.INPUT_MIME_TYPE, OpenInferenceMimeTypeValues.TEXT.value
        )
        run_span.set_attribute("zmeval.case_id", "case-1")
        run_span.set_attribute("zmeval.subject_outcome", "COMPLETED")
        run_span.set_attribute("zmeval.trace_complete", True)

        with tracer.start_as_current_span("file_edit") as e1:
            e1.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.TOOL.value
            )
            e1.set_attribute(SpanAttributes.TOOL_NAME, "edit")
            e1.set_attribute("zmeval.sequence", 1)
            e1.set_attribute("zmeval.event_type", "file_edit")

        with tracer.start_as_current_span("test_run") as e2:
            e2.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.TOOL.value
            )
            e2.set_attribute(SpanAttributes.TOOL_NAME, "pytest")
            e2.set_attribute("zmeval.sequence", 2)
            e2.set_attribute("zmeval.event_type", "test_run")
            e2.set_attribute(EXIT_CODE, 0)
            e2.set_attribute(VERIFIED, True)

        run_span.set_attribute(SpanAttributes.OUTPUT_VALUE, "69 passed")
    return run_span


span = emit_zmai_attempt(tracer)
trace_id = format(span.get_span_context().trace_id, "032x")
report("spans emitted", True, f"trace_id={trace_id}")

# flush before reading back
tracer_provider.force_flush()

print("\n=== reading back via client ===")
from phoenix.client import Client  # noqa: E402

client = Client(base_url=ENDPOINT)
try:
    spans = client.spans.get_spans(project_identifier="zmeval-trace-probe", trace_ids=[trace_id])
    report("spans read back", len(spans) >= 3, f"count={len(spans)}")
    for s in spans:
        nm = s.get("name") if isinstance(s, dict) else getattr(s, "name", "?")
        attrs = (s.get("attributes") if isinstance(s, dict) else getattr(s, "attributes", {})) or {}
        keys = [k for k in attrs if k.startswith("zmeval.") or k == EXIT_CODE]
        print(f"   span={nm} zmeval_attrs={keys}")
    # verify the custom attributes survived
    all_attrs = []
    for s in spans:
        a = (s.get("attributes") if isinstance(s, dict) else getattr(s, "attributes", {})) or {}
        all_attrs.append(a)
    merged = {k: v for a in all_attrs for k, v in a.items()}
    report(
        "case_id attribute survived",
        merged.get("zmeval.case_id") == "case-1",
        f"value={merged.get('zmeval.case_id')}",
    )
    report(
        "exit_code attribute survived",
        str(merged.get(EXIT_CODE)) == "0",
        f"value={merged.get(EXIT_CODE)}",
    )
except Exception as e:
    report("spans read back", False, f"{type(e).__name__}: {str(e)[:200]}")

print("\n=== DONE ===")
