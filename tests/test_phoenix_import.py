from pathlib import Path

import pytest

from zmevalhub.importers.ledger import open_ledger
from zmevalhub.importers.phoenix_import import (
    ImportConflict,
    RecoveryRequired,
    import_run,
    log_metric_version,
    read_metric_versions,
)
from zmevalhub.schemas.v1 import SourceRunV1


class FakeDatasets:
    def __init__(self):
        self.item = None
        self.calls = 0
        self.interrupt = False

    def get_dataset(self, *, dataset):
        if self.item is None:
            raise ValueError("Dataset not found")
        return self.item

    def create_dataset(self, *, name, dataframe, examples):
        self.calls += 1
        self.item = {"id": "dataset-1", "examples": [
            {"id": f"ex-{i}", **e} for i, e in enumerate(examples)]}
        if self.interrupt:
            self.interrupt = False
            raise ConnectionError("response lost after remote commit")
        return self.item

    def get_dataset_versions(self, *, dataset):
        return [{"version_id": "version-1"}]


class FakeExperiments:
    def __init__(self):
        self.item = None
        self.runs = []
        self.evaluations = []
        self.create_calls = 0
        self.run_calls = 0
        self.interrupt_run = False

    def list(self, *, dataset_id):
        return [self.item] if self.item else []

    def create(self, *, dataset_id, dataset_version_id, experiment_name,
               experiment_metadata):
        self.create_calls += 1
        self.item = {"id": "experiment-1", "name": experiment_name,
                     "experiment_metadata": experiment_metadata}
        return self.item

    def get_experiment(self, *, experiment_id):
        return {**self.item, "task_runs": self.runs,
                "evaluation_runs": self.evaluations}

    def log_run(self, **kwargs):
        self.run_calls += 1
        self.runs.append(kwargs)
        if self.interrupt_run:
            self.interrupt_run = False
            raise ConnectionError("response lost after remote run commit")

    def log_evaluation(self, **kwargs):
        self.evaluations = [e for e in self.evaluations if not (
            e["experiment_run_id"] == kwargs["experiment_run_id"]
            and e["name"] == kwargs["name"])]
        self.evaluations.append({**kwargs, "result": {"label": kwargs["label"]}})
        return {"id": str(len(self.evaluations))}


class FakeClient:
    def __init__(self):
        self.datasets = FakeDatasets()
        self.experiments = FakeExperiments()


@pytest.fixture
def run():
    path = Path(__file__).parent.parent / "fixtures/zmai/real_masked_coding_agent_pass.json"
    return SourceRunV1.model_validate_json(path.read_bytes())


def test_repeated_import_and_dataset_hash(run, tmp_path):
    client = FakeClient()
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    first = import_run(run, client, ledger)
    second = import_run(run, client, ledger)
    assert first.status == second.status == "COMPLETE"
    assert first.dataset_version_id == "version-1"
    assert len(first.dataset_content_sha256) == 64
    assert run.dataset.snapshot_sha256 is None
    assert (client.datasets.calls, client.experiments.create_calls,
            client.experiments.run_calls) == (1, 1, 1)


def test_completed_ledger_requires_remote_dataset(run, tmp_path):
    client = FakeClient()
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    import_run(run, client, ledger)
    client.datasets.item = None
    with pytest.raises(RecoveryRequired, match="dataset is missing"):
        import_run(run, client, ledger)
    assert (client.datasets.calls, client.experiments.create_calls) == (1, 1)


def test_completed_ledger_requires_remote_runs(run, tmp_path):
    client = FakeClient()
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    import_run(run, client, ledger)
    client.experiments.runs.clear()
    with pytest.raises(RecoveryRequired, match="run is missing"):
        import_run(run, client, ledger)
    assert client.experiments.run_calls == 1


def test_same_source_changed_content_conflicts(run, tmp_path):
    client = FakeClient()
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    import_run(run, client, ledger)
    changed = run.model_copy(deep=True)
    changed.cases[0].input["changed"] = True
    with pytest.raises(ImportConflict):
        import_run(changed, client, ledger)
    assert client.datasets.calls == 1


def test_lost_dataset_response_recovers_by_readback(run, tmp_path):
    client = FakeClient()
    client.datasets.interrupt = True
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    with pytest.raises(ConnectionError):
        import_run(run, client, ledger)
    result = import_run(run, client, ledger, resume=True)
    assert result.status == "COMPLETE"
    assert client.datasets.calls == 1


def test_ambiguous_missing_dataset_stops(run, tmp_path):
    client = FakeClient()
    client.datasets.interrupt = True
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    with pytest.raises(ConnectionError):
        import_run(run, client, ledger)
    client.datasets.item = None
    with pytest.raises(RecoveryRequired):
        import_run(run, client, ledger, resume=True)
    assert client.datasets.calls == 1


def test_remote_case_metadata_conflict_stops(run, tmp_path):
    client = FakeClient()
    client.datasets.interrupt = True
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    with pytest.raises(ConnectionError):
        import_run(run, client, ledger)
    client.datasets.item["examples"][0]["metadata"]["zmeval.kind"] = "rag_agent"
    with pytest.raises(ImportConflict):
        import_run(run, client, ledger, resume=True)


def test_lost_run_response_recovers_without_duplicate(run, tmp_path):
    client = FakeClient()
    client.experiments.interrupt_run = True
    ledger = open_ledger(str(tmp_path / "ledger.sqlite"))
    with pytest.raises(ConnectionError):
        import_run(run, client, ledger)
    assert import_run(run, client, ledger, resume=True).status == "COMPLETE"
    assert client.experiments.run_calls == 1


def test_metric_names_keep_independent_versions():
    client = FakeClient()
    client.experiments.item = {"id": "experiment-1"}
    log_metric_version(client, "run-1", "ZM-R001", "1", "FAIL")
    log_metric_version(client, "run-1", "ZM-R001", "2", "PASS")
    assert read_metric_versions(client, "experiment-1", "run-1", "ZM-R001") == {
        "1": "FAIL", "2": "PASS"}
    assert len(client.experiments.evaluations) == 2
