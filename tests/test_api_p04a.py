import json

from fastapi.testclient import TestClient
from test_comparison_p03a import bundle

from zmevalhub.api.app import create_app
from zmevalhub.cli.main import main


def test_openapi_catalog_provenance_and_historical_unknown():
    client = TestClient(create_app())
    assert client.get("/healthz").status_code == 200
    assert client.get("/docs").status_code == 200
    assert "/api/v1/runs" in client.get("/openapi.json").json()["paths"]
    response = client.get("/api/v1/runs?limit=20&offset=0")
    assert response.status_code == 200
    rows = response.json()["data"]
    masked = next(row for row in rows if row["source_run_id"] ==
                  "A1_echo_on_20261011_114528")
    assert masked["provenance"] == "real_masked"
    assert masked["evaluation_status"] == "UNKNOWN"
    assert any(row["provenance"] == "synthetic" for row in rows)
    run_id = masked["id"]
    evaluations = client.get(f"/api/v1/runs/{run_id}/evaluations").json()["data"]
    assert evaluations[0]["verdict"] == "UNKNOWN"
    detail = client.get(f"/api/v1/runs/{run_id}").json()["data"]
    case_id = detail["source_run"]["cases"][0]["case_id"]
    evidence = client.get(f"/api/v1/runs/{run_id}/evidence",
                          params={"case_id": case_id}).json()["data"]
    assert evidence["events"] and evidence["evidence_refs"]
    blocked = client.get("/api/v1/gates", params={"baseline_id": run_id,
                                                  "candidate_id": run_id}).json()
    assert blocked["data"]["status"] == "BLOCKED"


def test_rag_metrics_keep_missing_reference_unknown():
    client = TestClient(create_app())
    rows = client.get("/api/v1/runs").json()["data"]
    raw = next(row for row in rows if row["source_run_id"] ==
               "real_masked_phase09_checkpoint")
    metrics = client.get(f"/api/v1/runs/{raw['id']}/evaluations").json()["data"]
    recall = [item for item in metrics if item["metric_id"] == "evidence_recall"]
    answers = [item for item in metrics if item["metric_id"] == "answer_match"]
    assert [item["value"] for item in recall] == [1.0, 2 / 3]
    assert all(item["verdict"] == "UNKNOWN" and item["value"] is None
               for item in answers)


def test_comparison_gate_match_cli_and_invalid_inputs_are_rejected(tmp_path, capsys):
    baseline = bundle("base", ["PASS"] * 6)
    candidate = bundle("new", ["FAIL"] + ["PASS"] * 5)
    paths = [tmp_path / "baseline.json", tmp_path / "candidate.json"]
    for path, value in zip(paths, (baseline, candidate), strict=True):
        path.write_text(value.model_dump_json(), encoding="utf-8")
    client = TestClient(create_app(artifact_roots=[tmp_path]))
    rows = client.get("/api/v1/runs").json()["data"]
    ids = {row["source_run_id"]: row["id"] for row in rows}
    params = {"baseline_id": ids["base"], "candidate_id": ids["new"]}
    comparison = client.get("/api/v1/comparisons", params=params)
    assert comparison.status_code == 200
    assert comparison.json()["data"]["changes"][0]["change"] == "regressed"
    gate = client.get("/api/v1/gates", params=params)
    assert gate.status_code == 200 and gate.json()["data"]["status"] == "FAIL"
    assert gate.json()["data"]["findings"][0]["candidate_evidence_refs"] == [
        "new#event-1"]
    assert main(["gate", *map(str, paths), "--policy",
                 "config/gates/agent_regression_v1.json"]) == 1
    assert gate.json()["data"] == json.loads(capsys.readouterr().out)

    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 1, "cases": []}', encoding="utf-8")
    bad_row = next(row for row in client.get("/api/v1/runs").json()["data"]
                   if row["evaluation_status"] == "BLOCKED")
    invalid = client.get(f"/api/v1/runs/{bad_row['id']}")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "ZM_ARTIFACT_INVALID"
    assert client.get("/api/v1/runs/not-a-run-id").status_code == 404
    assert client.get("/api/v1/runs/../../pyproject.toml").status_code == 404
    bad_query = client.get("/api/v1/runs?limit=1000")
    assert bad_query.status_code == 422
    assert bad_query.json()["request_id"] == bad_query.headers["X-Request-ID"]


def test_api_difference_declaration_is_required(tmp_path):
    for name, model in (("baseline", "model-a"), ("candidate", "model-b")):
        (tmp_path / f"{name}.json").write_text(
            bundle(name, ["PASS"] * 6, model=model).model_dump_json(), encoding="utf-8")
    client = TestClient(create_app(artifact_roots=[tmp_path]))
    rows = client.get("/api/v1/runs").json()["data"]
    ids = {row["source_run_id"]: row["id"] for row in rows}
    pair = {"baseline_id": ids["baseline"], "candidate_id": ids["candidate"]}
    blocked = client.get("/api/v1/gates", params=pair).json()["data"]
    assert blocked["status"] == "BLOCKED"
    allowed = client.get("/api/v1/gates", params={**pair, "allow_difference": "model_id"})
    assert allowed.json()["data"]["status"] == "PASS"
