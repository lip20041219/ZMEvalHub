"""``zmeval`` CLI.

P0.0 exposes two commands only:

* ``zmeval validate <file>`` — validate a JSON file against the v1 contract.
* ``zmeval schema [--out PATH]`` — emit the JSON Schema.

Exit codes follow the blueprint's CI convention (§9.3): 0 success, 3 usage /
config error. A validation failure exits 1 so it can gate a pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from zmevalhub.schemas.v1 import model_json_schema
from zmevalhub.validation import validate_file

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 3


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return EXIT_USAGE

    result = validate_file(path)
    print(result.render())
    if args.json:
        print(
            json.dumps(
                {"ok": result.ok, "issues": [i.__dict__ for i in result.issues]},
                ensure_ascii=False,
                indent=2,
            )
        )
    return EXIT_OK if result.ok else EXIT_INVALID


def _cmd_schema(args: argparse.Namespace) -> int:
    schema = model_json_schema()
    text = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    else:
        sys.stdout.write(text)
    return EXIT_OK


def _cmd_import(args: argparse.Namespace) -> int:
    from zmevalhub.importers.ledger import open_ledger
    from zmevalhub.importers.phoenix_import import import_run
    from zmevalhub.schemas.v1 import SourceRunV1

    path = Path(args.file)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return EXIT_USAGE
    try:
        from phoenix.client import Client
    except ImportError:
        print("error: install the phoenix extra first", file=sys.stderr)
        return EXIT_USAGE
    try:
        data = path.read_bytes()
        run = SourceRunV1.model_validate_json(data)
        if run.source_sha256 is None:
            run = run.model_copy(update={"source_sha256": hashlib.sha256(data).hexdigest()})
        ledger_path = Path(args.ledger)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        row = import_run(run, Client(base_url=args.endpoint), open_ledger(str(ledger_path)),
                         resume=args.resume)
    except Exception as exc:
        print(f"import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INVALID
    print(json.dumps({"status": row.status, "content_sha256": row.content_sha256,
                      "dataset_content_sha256": row.dataset_content_sha256,
                      "dataset_id": row.dataset_id,
                      "dataset_version_id": row.dataset_version_id,
                      "experiment_id": row.experiment_id}, ensure_ascii=False))
    return EXIT_OK


def _cmd_evaluate_zmai(args: argparse.Namespace) -> int:
    from zmevalhub.importers.zmai_execution_log import ZmaiLogError, adapt_zmai_file
    from zmevalhub.rules.agent_reliability import (
        RuleResult,
        TraceSource,
        evaluate_all_agent_rules,
        trace_integrity,
    )
    from zmevalhub.schemas.v1 import Verdict

    proof_paths = (args.trace_proof_jsonl, args.trace_proof_sha256)
    if any(proof_paths) and not all(proof_paths):
        print("error: --trace-proof-jsonl and --trace-proof-sha256 must be used together",
              file=sys.stderr)
        return EXIT_USAGE
    try:
        run = adapt_zmai_file(args.file)
        source = None
        if all(proof_paths):
            source = TraceSource(
                ref=args.trace_proof_ref or str(args.trace_proof_jsonl),
                jsonl=Path(args.trace_proof_jsonl).read_bytes(),
                sha256=args.trace_proof_sha256,
            )
        results = [result for case in run.cases for attempt in case.attempts
                   for result in evaluate_all_agent_rules(case, attempt, source)]
        integrity = trace_integrity(run.cases[0].attempts[0], source)
        output_path = Path(args.output) if args.output else None
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
        payload = {
            "source_run": str(output_path) if output_path else run.model_dump(mode="json"),
            "trace_integrity": integrity.model_dump(mode="json"),
            "evaluations": [item.model_dump(mode="json") for item in results],
        }
    except (OSError, ValueError) as exc:
        message = f"ZMAI evaluation failed: {type(exc).__name__}: {exc}"
        if isinstance(exc, ZmaiLogError):
            results = [RuleResult(
                rule_id=rule_id,
                case_id=Path(args.file).name,
                attempt_index=0,
                verdict=Verdict.ERROR,
                reason=str(exc),
                evidence_refs=(str(args.file),),
            ) for rule_id in ("ZM-R001", "ZM-R002", "ZM-R003", "ZM-R004", "ZM-R005", "ZM-R006")]
            print(json.dumps({
                "status": "ERROR",
                "reason": str(exc),
                "evaluations": [item.model_dump(mode="json") for item in results],
            }, ensure_ascii=False, indent=2))
        else:
            print(message, file=sys.stderr)
        return EXIT_INVALID
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_INVALID if any(item.verdict.value == "ERROR" for item in results) else EXIT_OK


def _cmd_evaluate_zmwiki(args: argparse.Namespace) -> int:
    from zmevalhub.importers.zmwiki_benchmark import adapt_zmwiki_file
    from zmevalhub.rules.rag_deterministic import evaluate_rag_run, publish_rag_results

    if args.publish_run_map and not args.endpoint:
        print("ZMWiki evaluation failed: Phoenix endpoint is required", file=sys.stderr)
        return EXIT_INVALID
    try:
        run = adapt_zmwiki_file(args.file, dataset_path=args.dataset, arm=args.arm,
                                run_id=args.run_id)
        results = evaluate_rag_run(run)
        if args.publish_run_map:
            run_ids = json.loads(Path(args.publish_run_map).read_text(encoding="utf-8"))
            if not isinstance(run_ids, dict):
                raise ValueError("Phoenix run-ID map must be a JSON object")
            if set(run_ids) != {case.case_id for case in run.cases}:
                raise ValueError("Phoenix run-ID map must cover every case exactly")
            from phoenix.client import Client

            publish_rag_results(Client(base_url=args.endpoint), results, run_ids)
        output = Path(args.output) if args.output else None
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
        payload = {"source_run": str(output) if output else run.model_dump(mode="json"),
                   "evaluations": [item.model_dump(mode="json") for item in results]}
    except (OSError, ValueError, ImportError) as exc:
        print(f"ZMWiki evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INVALID
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_INVALID if any(item.verdict.value == "ERROR" for item in results) else EXIT_OK


def _cmd_evaluate_trace(args: argparse.Namespace) -> int:
    from zmevalhub.rules.agent_reliability import evaluate_and_publish, trace_integrity
    from zmevalhub.rules.trace_capture import load_capture
    from zmevalhub.schemas.v1 import AttemptV1, CaseV1, SubjectOutcome

    if args.publish_run_id is not None and not args.publish_run_id.strip():
        print("error: --publish-run-id requires a non-empty Phoenix experiment run ID",
              file=sys.stderr)
        return EXIT_USAGE

    try:
        events, source = load_capture(args.events, args.proof)
        claimed = events[-1].payload.get("claimed", "UNKNOWN")
        outcome = SubjectOutcome(claimed)
        attempt = AttemptV1(attempt_index=0, subject_outcome=outcome,
                            events=events, trace_complete=events[-1].status == "ok")
        case = CaseV1(case_id=args.case_id, kind="coding_agent", attempts=[attempt])
        client = None
        if args.publish_run_id:
            from phoenix.client import Client

            client = Client(base_url=args.endpoint)
        results = evaluate_and_publish(case, attempt, source, client=client,
                                       experiment_run_id=args.publish_run_id)
        payload = {"trace_integrity": trace_integrity(attempt, source).model_dump(),
                   "evaluations": [item.model_dump(mode="json") for item in results]}
    except (OSError, ValueError, ImportError) as exc:
        print(f"trace evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INVALID
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_INVALID if any(item.verdict.value == "ERROR" for item in results) else EXIT_OK


def _cmd_compare(args: argparse.Namespace) -> int:
    from zmevalhub.comparison import EvalBundle, compare_bundles

    try:
        baseline = EvalBundle.model_validate_json(Path(args.baseline).read_bytes())
        candidate = EvalBundle.model_validate_json(Path(args.candidate).read_bytes())
        result = compare_bundles(baseline, candidate,
                                 allowed_differences=frozenset(args.allow_difference))
    except (OSError, ValueError) as exc:
        print(f"comparison input failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INVALID
    print(result.model_dump_json(indent=2))
    return EXIT_OK if result.comparable else EXIT_INVALID


def _cmd_gate(args: argparse.Namespace) -> int:
    from zmevalhub.comparison import EvalBundle
    from zmevalhub.gate import GateDecision, GatePolicy, gate_bundles

    try:
        policy = GatePolicy.model_validate_json(Path(args.policy).read_bytes())
        baseline = EvalBundle.model_validate_json(Path(args.baseline).read_bytes())
        candidate = EvalBundle.model_validate_json(Path(args.candidate).read_bytes())
        decision = gate_bundles(baseline, candidate, policy,
                                allowed_differences=frozenset(args.allow_difference))
    except (OSError, ValueError) as exc:
        decision = GateDecision(status="BLOCKED", policy_name=None, policy_version=None,
                                baseline_run_id=None, candidate_run_id=None,
                                reasons=[f"gate input invalid: {type(exc).__name__}: {exc}"],
                                findings=[], checked_changes=[])
    print(decision.model_dump_json(indent=2))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[decision.status]


def _cmd_watch_zmai(args: argparse.Namespace) -> int:
    from zmevalhub.paired_capture import RunSpec, watch_zmai_run

    try:
        spec = RunSpec.model_validate_json(Path(args.spec).read_bytes())
        proof = watch_zmai_run(
            spec, args.directory, args.log,
            poll_seconds=args.poll_ms / 1000, timeout_seconds=args.timeout_seconds,
            on_ready=lambda: print(f"capture ready; start ZMAI now: {args.log}",
                                   file=sys.stderr, flush=True),
        )
    except (OSError, ValueError, TimeoutError) as exc:
        print(json.dumps({"status": "BLOCKED", "reasons": [str(exc)]}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "SEALED", "proof": str(proof)}, ensure_ascii=False))
    return 0


def _cmd_pair_captures(args: argparse.Namespace) -> int:
    from zmevalhub.comparison import compare_bundles
    from zmevalhub.gate import GatePolicy, evaluate_gate
    from zmevalhub.paired_capture import load_run_capture

    try:
        policy = GatePolicy.model_validate_json(Path(args.policy).read_bytes())
        baseline = load_run_capture(args.baseline)
        candidate = load_run_capture(args.candidate)
        comparison = compare_bundles(
            baseline, candidate, allowed_differences=frozenset(args.allow_difference))
        decision = evaluate_gate(comparison, policy)
        bundles = None
        if args.bundle_dir:
            output = Path(args.bundle_dir)
            output.mkdir(parents=True, exist_ok=False)
            paths = [output / "baseline.json", output / "candidate.json"]
            for path, bundle in zip(paths, (baseline, candidate), strict=True):
                path.write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
            bundles = [str(path) for path in paths]
        payload = {"comparison": comparison.model_dump(mode="json"),
                   "gate": decision.model_dump(mode="json"), "bundles": bundles}
        status = decision.status
    except (OSError, ValueError) as exc:
        payload = {"comparison": None,
                   "gate": {"status": "BLOCKED", "policy_name": None,
                            "policy_version": None, "reasons": [str(exc)],
                            "findings": [], "checked_changes": []},
                   "bundles": None}
        status = "BLOCKED"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zmeval", description="ZMEvalHub CLI (P0.0)")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="Validate a JSON file against schema_version=1")
    v.add_argument("file", help="Path to the JSON file")
    v.add_argument("--json", action="store_true", help="Also emit machine-readable issues")
    v.set_defaults(func=_cmd_validate)

    s = sub.add_parser("schema", help="Print or write the JSON Schema")
    s.add_argument("--out", help="Write schema JSON to this path instead of stdout")
    s.set_defaults(func=_cmd_schema)

    i = sub.add_parser("import", help="Idempotently import a SourceRunV1 JSON file")
    i.add_argument("file")
    i.add_argument("--to", choices=["phoenix"], required=True)
    i.add_argument("--ledger", default=".zmevalhub/imports.sqlite")
    i.add_argument("--endpoint", default=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT",
                                                      "http://127.0.0.1:6006"))
    i.add_argument("--resume", action="store_true", help="Reconcile an interrupted import")
    i.set_defaults(func=_cmd_import)

    z = sub.add_parser("evaluate-zmai", help="Convert and offline-evaluate a ZMAI execution log")
    z.add_argument("file", help="Path to an external .state/execution_log.json")
    z.add_argument("--output", help="Write the normalized SourceRunV1 JSON to this path")
    z.add_argument("--trace-proof-jsonl", help="Upstream-captured normalized EventV1 JSONL")
    z.add_argument("--trace-proof-sha256", help="SHA-256 recorded by the upstream producer")
    z.add_argument("--trace-proof-ref", help="Reference identifying the upstream proof")
    z.set_defaults(func=_cmd_evaluate_zmai)

    wiki = sub.add_parser("evaluate-zmwiki", help="Read-only ZMWiki Benchmark JSONL RAG checks")
    wiki.add_argument("file", help="ZMWiki checkpoint JSONL")
    wiki.add_argument("--dataset", help="Dataset JSON with reference answers")
    wiki.add_argument("--arm", choices=["rag", "agent"],
                      help="Required for nested comparison checkpoints")
    wiki.add_argument("--run-id", help="Stable source run ID; defaults to filename and arm")
    wiki.add_argument("--output", help="Write normalized SourceRunV1 JSON")
    wiki.add_argument("--publish-run-map", help="JSON map: case_id to Phoenix run ID")
    wiki.add_argument("--endpoint", default=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT",
                                                         "http://127.0.0.1:6006"))
    wiki.set_defaults(func=_cmd_evaluate_zmwiki)

    t = sub.add_parser("evaluate-trace", help="Evaluate a sealed new-run Trace offline")
    t.add_argument("events", help="Collector EventV1 JSONL")
    t.add_argument("proof", help="Collector proof JSON")
    t.add_argument("--case-id", required=True)
    t.add_argument("--publish-run-id", help="Publish six evaluations to an existing Phoenix run")
    t.add_argument("--endpoint", default=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT",
                                                      "http://127.0.0.1:6006"))
    t.set_defaults(func=_cmd_evaluate_trace)

    c = sub.add_parser("compare", help="Compare two offline evaluation bundles")
    c.add_argument("baseline", help="Baseline EvalBundle JSON")
    c.add_argument("candidate", help="Candidate EvalBundle JSON")
    c.add_argument("--allow-difference", action="append", default=[],
                   choices=["git_sha", "model_id", "config_sha256", "prompt_version"],
                   help="Explicitly permit this subject version difference")
    c.set_defaults(func=_cmd_compare)

    g = sub.add_parser("gate", help="Apply a versioned offline paired quality gate")
    g.add_argument("baseline", help="Baseline EvalBundle JSON")
    g.add_argument("candidate", help="Candidate EvalBundle JSON")
    g.add_argument("--policy", required=True, help="Versioned GatePolicy JSON")
    g.add_argument("--allow-difference", action="append", default=[],
                   choices=["git_sha", "model_id", "config_sha256", "prompt_version"],
                   help="Explicitly permit this subject version difference")
    g.set_defaults(func=_cmd_gate)

    w = sub.add_parser("watch-zmai", help="Capture one fresh ZMAI run while it executes")
    w.add_argument("spec", help="Run-start metadata JSON")
    w.add_argument("directory", help="New capture directory")
    w.add_argument("--log", required=True, help="Fresh ZMAI execution_log.json path")
    w.add_argument("--poll-ms", type=int, default=200)
    w.add_argument("--timeout-seconds", type=float, default=3600)
    w.set_defaults(func=_cmd_watch_zmai)

    pair = sub.add_parser("pair-captures", help="Evaluate, compare, and gate two sealed runs")
    pair.add_argument("baseline", help="Baseline capture directory")
    pair.add_argument("candidate", help="Candidate capture directory")
    pair.add_argument("--policy", required=True, help="Versioned GatePolicy JSON")
    pair.add_argument("--allow-difference", action="append", default=[],
                      choices=["git_sha", "model_id", "config_sha256", "prompt_version"])
    pair.add_argument("--bundle-dir", help="Write verified EvalBundle JSON files here")
    pair.set_defaults(func=_cmd_pair_captures)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
