import json

import pytest

from zmevalhub.cli.main import main
from zmevalhub.gate import GatePolicy
from zmevalhub.paired_capture import RunSpec, load_run_capture, watch_zmai_run


def spec(run_id, *, task="fix", model="model-a", seed=7):
    return RunSpec(
        source_run_id=run_id, source_id=run_id, dataset_name="fixed-case",
        case={"case_id": "case-1", "kind": "coding_agent", "input": {"task": task},
              "expected": {"tests": "pass"}},
        subject={"name": "ZMAI", "model_id": model},
        conditions={"seed": seed, "repetitions": 1, "concurrency": 1,
                    "timeout_ms": 30000, "tool_environment_sha256": "a" * 64,
                    "evaluator_config_sha256": "b" * 64, "prompt_version": "p1"},
    )


def zmai_log(exit_code=0):
    steps = [
        {"step_id": 1, "phase": "fix_driving", "action": "edit", "success": True},
        {"step_id": 2, "phase": "tool_call", "action": "shell_exec", "success": True,
         "tool_name": "shell_exec", "tool_input": {"command": "pytest tests/test_case.py -q"}},
        {"step_id": 3, "phase": "tool_result", "action": "shell_exec", "success": True,
         "tool_name": "shell_exec", "error": f"exit {exit_code}: test result"},
        {"step_id": 4, "phase": "finalize", "action": "agent_finalize", "success": True,
         "metadata": {"status": "completed"}},
    ]
    return json.dumps({"agent_id": "agent-7", "created_at": "2026-11-12T10:00:00Z",
                       "step_count": len(steps), "steps": steps}).encode()


def captured(tmp_path, run_id, exit_code=0, *, task="fix"):
    directory = tmp_path / run_id
    log_path = tmp_path / f"{run_id}.json"
    watch_zmai_run(spec(run_id, task=task), directory, log_path,
                   poll_seconds=0.001, timeout_seconds=0.2,
                   on_ready=lambda: log_path.write_bytes(zmai_log(exit_code)))
    return directory


def test_live_capture_builds_standard_bundles_and_passes_gate(tmp_path, capsys):
    baseline = captured(tmp_path, "base")
    candidate = captured(tmp_path, "new")
    bundle = load_run_capture(baseline)
    assert bundle.source_run.dataset.snapshot_sha256
    assert len(bundle.evaluations) == 6
    assert bundle.evaluations[1].evidence_refs == ("capture:base#event-4",
                                                   "capture:base#event-5")
    policy = tmp_path / "policy.json"
    policy.write_text(GatePolicy(schema_version=1, name="regression", version="1")
                      .model_dump_json(), encoding="utf-8")
    outputs = tmp_path / "bundles"
    assert main(["pair-captures", str(baseline), str(candidate), "--policy", str(policy),
                 "--bundle-dir", str(outputs)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gate"]["status"] == "PASS"
    assert payload["comparison"]["changes"][0]["rule_version"] == "1"
    assert (outputs / "baseline.json").is_file()


def test_confirmed_regression_fails_and_missing_exit_blocks(tmp_path, capsys):
    baseline = captured(tmp_path, "base")
    failed = captured(tmp_path, "failed", exit_code=1)
    unknown = captured(tmp_path, "unknown", exit_code="missing")
    policy = tmp_path / "policy.json"
    policy.write_text(GatePolicy(schema_version=1, name="regression", version="1")
                      .model_dump_json(), encoding="utf-8")
    args = ["pair-captures", str(baseline), str(failed), "--policy", str(policy)]
    assert main(args) == 1
    failed_output = json.loads(capsys.readouterr().out)
    assert failed_output["gate"]["findings"]
    args[2] = str(unknown)
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["gate"]["status"] == "BLOCKED"


def test_snapshot_tamper_and_historical_replay_are_refused(tmp_path, capsys):
    baseline = captured(tmp_path, "base")
    candidate = captured(tmp_path, "new", task="different")
    policy = tmp_path / "policy.json"
    policy.write_text(GatePolicy(schema_version=1, name="regression", version="1")
                      .model_dump_json(), encoding="utf-8")
    args = ["pair-captures", str(baseline), str(candidate), "--policy", str(policy)]
    assert main(args) == 2
    assert "snapshot" in capsys.readouterr().out
    original_log = candidate / "source_execution_log.json"
    original_log.write_bytes(original_log.read_bytes() + b" ")
    assert main(args) == 2
    assert "ZMAI log bytes" in capsys.readouterr().out
    (candidate / "metadata.json").write_bytes(b"{}")
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["comparison"] is None
    existing = tmp_path / "existing.json"
    existing.write_bytes(zmai_log())
    with pytest.raises(ValueError, match="historical replay"):
        watch_zmai_run(spec("old"), tmp_path / "old", existing,
                       timeout_seconds=0.01)
    missing = json.loads(zmai_log())
    missing.pop("agent_id")
    missing_path = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="agent ID"):
        watch_zmai_run(spec("missing"), tmp_path / "missing", missing_path,
                       poll_seconds=0.001, timeout_seconds=0.1,
                       on_ready=lambda: missing_path.write_text(json.dumps(missing),
                                                                encoding="utf-8"))


def test_new_workspace_log_glob_is_discovered(tmp_path):
    log_path = tmp_path / "workspace" / "agent_1" / ".state" / "execution_log.json"

    def start_run():
        log_path.parent.mkdir(parents=True)
        log_path.write_bytes(zmai_log())

    pattern = tmp_path / "workspace" / "agent_*" / ".state" / "execution_log.json"
    watch_zmai_run(spec("glob"), tmp_path / "glob", pattern,
                   poll_seconds=0.001, timeout_seconds=0.2, on_ready=start_run)
    assert load_run_capture(tmp_path / "glob").source_run.source_run_id == "glob"


def test_uncontrolled_seed_is_captured_but_blocks_gate(tmp_path, capsys):
    directories = []
    for run_id in ("base", "new"):
        log_path = tmp_path / f"{run_id}.json"
        directory = tmp_path / run_id
        watch_zmai_run(spec(run_id, seed=None), directory, log_path,
                       poll_seconds=0.001, timeout_seconds=0.2,
                       on_ready=lambda path=log_path: path.write_bytes(zmai_log()))
        directories.append(directory)
    policy = tmp_path / "policy.json"
    policy.write_text(GatePolicy(schema_version=1, name="regression", version="1")
                      .model_dump_json(), encoding="utf-8")
    assert main(["pair-captures", *map(str, directories), "--policy", str(policy)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert any("seed" in reason for reason in payload["comparison"]["reasons"])
