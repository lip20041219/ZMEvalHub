"""Idempotent, recoverable SourceRunV1 import into Phoenix.

SQLite commits *before* each remote write. An ambiguous remote outcome is never
replayed blindly: retry reads Phoenix first or raises RecoveryRequired.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from zmevalhub.importers.ledger import ImportLedger
from zmevalhub.importers.phoenix_mapping import plan_import
from zmevalhub.schemas.v1 import SourceRunV1


class ImportConflict(ValueError):
    pass


class RecoveryRequired(RuntimeError):
    pass


def _value(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _canonical(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def dataset_sha256(run: SourceRunV1) -> str:
    """Hash only the ordered public case content; never invent a source snapshot hash."""
    cases = [{"case_id": c.case_id, "input": c.input, "expected": c.expected,
              "kind": c.kind.value, "tags": c.tags} for c in run.cases]
    ordered = sorted(cases, key=lambda case: case["case_id"])
    return hashlib.sha256(_canonical(ordered).encode()).hexdigest()


def metric_name(metric_id: str, metric_version: str) -> str:
    """Distinct Phoenix names preserve revisions; identical names upsert."""
    if not metric_id or not metric_version or "@" in metric_id or "@" in metric_version:
        raise ValueError("metric_id and metric_version must be nonempty and cannot contain '@'")
    return f"{metric_id}@{metric_version}"


def log_metric_version(client: Any, experiment_run_id: str, metric_id: str,
                       metric_version: str, label: str, *,
                       explanation: str | None = None,
                       metadata: dict[str, Any] | None = None) -> Any:
    """Use Phoenix's name key so a new rule version cannot overwrite an older one."""
    if label not in {"PASS", "FAIL", "UNKNOWN", "ERROR", "SKIPPED"}:
        raise ValueError("invalid verdict label")
    kwargs: dict[str, Any] = {}
    if explanation is not None:
        kwargs["explanation"] = explanation
    if metadata is not None:
        kwargs["metadata"] = metadata
    return client.experiments.log_evaluation(
        experiment_run_id=experiment_run_id, name=metric_name(metric_id, metric_version),
        label=label, annotator_kind="CODE", **kwargs)


def read_metric_versions(client: Any, experiment_id: str, experiment_run_id: str,
                         metric_id: str) -> dict[str, str]:
    """Read each version independently from Phoenix's persisted evaluation names."""
    prefix = metric_name(metric_id, "v")[:-1]
    result: dict[str, str] = {}
    experiment = client.experiments.get_experiment(experiment_id=experiment_id)
    for evaluation in _value(experiment, "evaluation_runs") or []:
        name = _value(evaluation, "name")
        if (_value(evaluation, "experiment_run_id") != experiment_run_id
                or not isinstance(name, str) or not name.startswith(prefix)):
            continue
        version = name[len(prefix):]
        if not version or version in result:
            raise ImportConflict("ambiguous Phoenix metric version: " + name)
        value = _value(evaluation, "result")
        result[version] = _value(value, "label")
    return result


def _get_dataset(client: Any, name: str) -> Any | None:
    try:
        return client.datasets.get_dataset(dataset=name)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            return None
        raise
    except Exception as exc:
        if getattr(getattr(exc, "response", None), "status_code", None) == 404:
            return None
        raise


def _set(session_factory: Any, row_id: int, status: str, **fields: Any) -> None:
    with session_factory.begin() as session:
        row = session.get(ImportLedger, row_id)
        for key, value in fields.items():
            setattr(row, key, value)
        row.status = status


def _verify_examples(dataset: Any, planned: list[dict[str, Any]]) -> dict[str, str]:
    actual = list(_value(dataset, "examples") or [])
    by_case: dict[str, str] = {}
    expected = {e["metadata"]["zmeval.case_id"]: e for e in planned}
    for example in actual:
        meta = _value(example, "metadata") or {}
        case_id = meta.get("zmeval.case_id")
        if case_id not in expected or case_id in by_case:
            raise ImportConflict("Phoenix dataset examples differ from the requested content")
        want = expected[case_id]
        if (_canonical(_value(example, "input")) != _canonical(want["input"])
                or _canonical(_value(example, "output")) != _canonical(want["output"])
                or any(_canonical(meta.get(key)) != _canonical(value)
                       for key, value in want["metadata"].items())):
            raise ImportConflict("Phoenix dataset case content differs: " + case_id)
        by_case[case_id] = _value(example, "id")
    if set(by_case) != set(expected) or not all(by_case.values()):
        raise ImportConflict("Phoenix dataset case IDs differ from the requested content")
    return by_case


def _read_runs(client: Any, experiment_id: str) -> list[Any]:
    experiment = client.experiments.get_experiment(experiment_id=experiment_id)
    return list(_value(experiment, "task_runs") or [])


def _verify_complete(client: Any, row: ImportLedger, dataset_name: str,
                     experiment_name: str, plan: dict[str, Any]) -> None:
    """Never trust a COMPLETE ledger row without reading its Phoenix resources."""
    dataset = _get_dataset(client, dataset_name)
    if dataset is None or _value(dataset, "id") != row.dataset_id:
        raise RecoveryRequired("completed import dataset is missing or has a different ID")
    case_to_example = _verify_examples(dataset, plan["examples"])
    versions = client.datasets.get_dataset_versions(dataset=row.dataset_id)
    if len(versions) != 1 or _value(versions[0], "version_id") != row.dataset_version_id:
        raise RecoveryRequired("completed import dataset version is missing or changed")
    experiments = [e for e in client.experiments.list(dataset_id=row.dataset_id)
                   if _value(e, "name") == experiment_name]
    if len(experiments) != 1 or _value(experiments[0], "id") != row.experiment_id:
        raise RecoveryRequired("completed import experiment is missing or changed")
    details = client.experiments.get_experiment(experiment_id=row.experiment_id)
    metadata = _value(details, "experiment_metadata") or _value(details, "metadata") or {}
    if (metadata.get("zmeval.content_sha256") != row.content_sha256
            or metadata.get("zmeval.dataset.content_sha256") != row.dataset_content_sha256):
        raise ImportConflict("completed import Phoenix metadata differs from ledger")
    actual: dict[str, Any] = {}
    for item in _value(details, "task_runs") or []:
        key = f"{_value(item, 'dataset_example_id')}:{_value(item, 'repetition_number')}"
        if key in actual:
            raise ImportConflict("duplicate Phoenix run key: " + key)
        actual[key] = item
    expected_keys = set()
    for planned in plan["runs"]:
        key = f"{case_to_example[planned['case_id']]}:{planned['repetition_number']}"
        expected_keys.add(key)
        recorded = actual.get(key)
        if recorded is None:
            raise RecoveryRequired("completed import Phoenix run is missing: " + key)
        if (planned["error"] != _value(recorded, "error")
                or (not planned["error"] and
                    _canonical(planned["output"]) != _canonical(_value(recorded, "output")))):
            raise ImportConflict("completed import Phoenix run differs: " + key)
    if set(actual) != expected_keys:
        raise ImportConflict("completed import has unexpected Phoenix runs")


def import_run(run: SourceRunV1, client: Any, session_factory: Any,
               *, resume: bool = False) -> ImportLedger:
    """Import once. Retry interrupted work with ``resume=True`` after the prior worker stops."""
    plan = plan_import(run)
    content_hash = run.content_sha256()
    dataset_hash = dataset_sha256(run)
    identity = (run.source, run.source_run_id, run.importer_version)
    suffix = hashlib.sha256(_canonical((*identity, content_hash)).encode()).hexdigest()[:24]
    dataset_name = f"zmeval-{suffix}"
    experiment_name = f"zmeval-import-{suffix}"

    with session_factory.begin() as session:
        row = session.scalar(select(ImportLedger).where(
            ImportLedger.source == identity[0], ImportLedger.source_run_id == identity[1],
            ImportLedger.importer_version == identity[2]))
        if row is None:
            row = ImportLedger(source=identity[0], source_run_id=identity[1],
                               importer_version=identity[2], source_sha256=run.source_sha256,
                               content_sha256=content_hash, dataset_content_sha256=dataset_hash,
                               status="PENDING")
            session.add(row)
            session.flush()
        elif row.content_sha256 != content_hash or row.dataset_content_sha256 != dataset_hash:
            raise ImportConflict("same source run and importer version has different content")
        elif row.status != "COMPLETE" and not resume:
            raise RecoveryRequired(
                "import is unfinished; retry with resume=True after prior worker stops")
        row_id = row.id
        prior_status = row.status
        if prior_status == "COMPLETE":
            _verify_complete(client, row, dataset_name, experiment_name, plan)
            return row

    dataset = _get_dataset(client, dataset_name)
    if dataset is None:
        if prior_status == "DATASET_CALL":
            raise RecoveryRequired("dataset create outcome ambiguous; inspect Phoenix before retry")
        _set(session_factory, row_id, "DATASET_CALL")
        client.datasets.create_dataset(name=dataset_name, dataframe=None, examples=plan["examples"])
        dataset = _get_dataset(client, dataset_name)
        if dataset is None:
            raise RecoveryRequired("created dataset is not readable; outcome ambiguous")
    case_to_example = _verify_examples(dataset, plan["examples"])
    dataset_id = _value(dataset, "id")
    versions = client.datasets.get_dataset_versions(dataset=dataset_id)
    if len(versions) != 1 or not _value(versions[0], "version_id"):
        raise ImportConflict("dedicated Phoenix dataset has ambiguous versions")
    version_id = _value(versions[0], "version_id")
    _set(session_factory, row_id, "DATASET_READY", dataset_id=dataset_id,
         dataset_version_id=version_id)

    experiments = [e for e in client.experiments.list(dataset_id=dataset_id)
                   if _value(e, "name") == experiment_name]
    if len(experiments) > 1:
        raise ImportConflict("multiple Phoenix experiments have the deterministic import name")
    if experiments:
        experiment_id = _value(experiments[0], "id")
        details = client.experiments.get_experiment(experiment_id=experiment_id)
        metadata = _value(details, "experiment_metadata") or _value(details, "metadata") or {}
        if metadata.get("zmeval.content_sha256") != content_hash:
            raise ImportConflict("existing Phoenix experiment has different content")
    else:
        if prior_status == "EXPERIMENT_CALL":
            raise RecoveryRequired(
                "experiment create outcome ambiguous; inspect Phoenix before retry")
        _set(session_factory, row_id, "EXPERIMENT_CALL")
        metadata = {**plan["experiment_metadata"],
                    "zmeval.dataset.content_sha256": dataset_hash}
        created = client.experiments.create(dataset_id=dataset_id,
                                            dataset_version_id=version_id,
                                            experiment_name=experiment_name,
                                            experiment_metadata=metadata)
        experiment_id = _value(created, "id")
        if not experiment_id:
            raise RecoveryRequired("Phoenix returned no experiment ID")
    _set(session_factory, row_id, "EXPERIMENT_READY", experiment_id=experiment_id)

    with session_factory() as session:
        inflight = session.get(ImportLedger, row_id).inflight_run_key
    existing: dict[str, Any] = {}
    for item in _read_runs(client, experiment_id):
        key = f"{_value(item, 'dataset_example_id')}:{_value(item, 'repetition_number')}"
        if key in existing:
            raise ImportConflict("duplicate Phoenix run key: " + key)
        existing[key] = item
    if inflight and inflight not in existing:
        raise RecoveryRequired("run write outcome ambiguous: " + inflight)

    for planned in plan["runs"]:
        key = f"{case_to_example[planned['case_id']]}:{planned['repetition_number']}"
        recorded = existing.get(key)
        if recorded is not None:
            if (planned["error"] != _value(recorded, "error")
                    or (not planned["error"] and
                        _canonical(planned["output"]) != _canonical(_value(recorded, "output")))):
                raise ImportConflict("Phoenix run content differs: " + key)
            continue
        _set(session_factory, row_id, "RUNS", inflight_run_key=key)
        now = datetime.now(UTC)
        client.experiments.log_run(experiment_id=experiment_id,
                                   dataset_example_id=case_to_example[planned["case_id"]],
                                   output=planned["output"], start_time=now,
                                   end_time=now + timedelta(milliseconds=1),
                                   repetition_number=planned["repetition_number"],
                                   error=planned["error"])
        _set(session_factory, row_id, "RUNS", inflight_run_key=None)

    if len(_read_runs(client, experiment_id)) != len(plan["runs"]):
        raise RecoveryRequired("Phoenix run readback is incomplete")
    _set(session_factory, row_id, "COMPLETE", inflight_run_key=None)
    with session_factory() as session:
        return session.get(ImportLedger, row_id)
