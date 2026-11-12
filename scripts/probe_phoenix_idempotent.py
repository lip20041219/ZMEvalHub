"""Manual Phoenix acceptance: isolated synthetic data and a fresh SQLite ledger."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from zmevalhub.importers.ledger import ImportLedger, open_ledger
from zmevalhub.importers.phoenix_import import (
    ImportConflict,
    RecoveryRequired,
    dataset_sha256,
    import_run,
)
from zmevalhub.schemas.v1 import SourceRunV1


def value(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def require(ok, reason):
    if not ok:
        raise AssertionError(reason)


def remote_state(client, row):
    dataset = client.datasets.get_dataset(dataset=row.dataset_id)
    versions = client.datasets.get_dataset_versions(dataset=row.dataset_id)
    experiments = [e for e in client.experiments.list(dataset_id=row.dataset_id)
                   if value(e, "id") == row.experiment_id]
    require(len(experiments) == 1, "Phoenix experiment ID is missing or duplicated")
    details = client.experiments.get_experiment(experiment_id=row.experiment_id)
    return (value(dataset, "id"), tuple(value(v, "version_id") for v in versions),
            value(experiments[0], "id"), len(value(details, "task_runs") or []))


class SimulatedInterrupt(Exception):
    pass


class InterruptedDatasets:
    def __init__(self, real, *, after_commit):
        self.real = real
        self.after_commit = after_commit
        self.name = None
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.real, name)

    def create_dataset(self, **kwargs):
        self.calls += 1
        self.name = kwargs["name"]
        if self.after_commit:
            self.real.create_dataset(**kwargs)
        raise SimulatedInterrupt("simulated lost dataset-create response")


class ClientProxy:
    def __init__(self, real, datasets):
        self.datasets = datasets
        self.experiments = real.experiments


def ledger_row(factory, run):
    with factory() as session:
        return session.scalar(select(ImportLedger).where(
            ImportLedger.source == run.source,
            ImportLedger.source_run_id == run.source_run_id,
            ImportLedger.importer_version == run.importer_version))


def main():
    from phoenix.client import Client

    root = Path(__file__).resolve().parent.parent
    fixture = root / "fixtures/synthetic/synthetic_unknown_evidence.json"
    original = SourceRunV1.model_validate_json(fixture.read_bytes())
    probe_id = uuid4().hex
    run = original.model_copy(update={"source": "zmeval-acceptance-probe",
                                      "source_run_id": probe_id + "-first"})
    directory = root / ".zmevalhub" / "acceptance" / probe_id
    directory.mkdir(parents=True, exist_ok=False)
    factory = open_ledger(str(directory / "imports.sqlite"))
    client = Client(base_url=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT",
                                        "http://127.0.0.1:6006"))
    print("probe_id:", probe_id, "ledger:", directory / "imports.sqlite")

    stage = "first import"
    try:
        first = import_run(run, client, factory)
        require(first.status == "COMPLETE" and first.dataset_id and first.experiment_id,
                "first import did not complete with remote IDs")
        require(first.dataset_content_sha256 == dataset_sha256(run)
                and first.dataset_version_id, "dataset hash/version mapping is missing")
        before = remote_state(client, first)
        require(before == (first.dataset_id, (first.dataset_version_id,),
                           first.experiment_id, 1), "first import ledger/Phoenix mismatch")
        print("PASS first import: ledger and Phoenix IDs, version, hash and run agree")

        stage = "repeat import"
        again = import_run(run, client, factory)
        require(again.id == first.id and remote_state(client, again) == before,
                "repeat import changed ledger identity or Phoenix resources")
        print("PASS repeat import: no extra dataset version, experiment or run")

        stage = "same-source conflict"
        changed = run.model_copy(deep=True)
        changed.cases[0].input["different-content"] = True
        try:
            import_run(changed, client, factory)
        except ImportConflict:
            pass
        else:
            raise AssertionError("same-source changed content was accepted")
        require(remote_state(client, first) == before,
                "conflict changed Phoenix resources")
        print("PASS same-source conflict: rejected without remote writes")

        stage = "interruption after remote dataset write"
        interrupted = run.model_copy(update={"source_run_id": probe_id + "-resume"})
        dropped = InterruptedDatasets(client.datasets, after_commit=True)
        try:
            import_run(interrupted, ClientProxy(client, dropped), factory)
        except SimulatedInterrupt:
            pass
        else:
            raise AssertionError("simulated interruption did not occur")
        pending = ledger_row(factory, interrupted)
        require(pending.status == "DATASET_CALL" and dropped.calls == 1,
                "interruption marker was not committed before remote write")
        require(value(client.datasets.get_dataset(dataset=dropped.name), "id"),
                "remote dataset was not committed before simulated lost reply")
        recovered = import_run(interrupted, client, factory, resume=True)
        require(recovered.status == "COMPLETE" and dropped.calls == 1,
                "resume did not complete from existing remote dataset")
        require(remote_state(client, recovered) ==
                (recovered.dataset_id, (recovered.dataset_version_id,),
                 recovered.experiment_id, 1), "resumed ledger/Phoenix mismatch")
        print("PASS --resume: lost reply recovered; one dataset version, experiment and run")

        stage = "unknown remote outcome"
        uncertain = run.model_copy(update={"source_run_id": probe_id + "-unknown"})
        blocked = InterruptedDatasets(client.datasets, after_commit=False)
        try:
            import_run(uncertain, ClientProxy(client, blocked), factory)
        except SimulatedInterrupt:
            pass
        else:
            raise AssertionError("simulated interruption did not occur")
        try:
            import_run(uncertain, client, factory, resume=True)
        except RecoveryRequired:
            pass
        else:
            raise AssertionError("unknown remote outcome was reported as success")
        require(ledger_row(factory, uncertain).status != "COMPLETE",
                "ambiguous remote state was marked COMPLETE")
        print("PASS unknown remote outcome: remains unfinished, no false success")
    except Exception as exc:
        print(f"FAIL {stage}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("PASS Phoenix online idempotent import acceptance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
