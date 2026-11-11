"""Probe: evaluation/verdict semantics in Phoenix (overwrite vs accumulate)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from phoenix.client import Client

c = Client(base_url=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006"))


def g(obj, *keys, default=None):
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            return obj[k]
        if hasattr(obj, k):
            return getattr(obj, k)
    return default


ds = c.datasets.create_dataset(
    name="verdict-probe3",
    dataframe=None,
    examples=[{"input": {"q": "x"}, "output": {"a": "y"}}],
)
ds_id = g(ds, "id")

exp = c.experiments.create(dataset_id=ds_id, experiment_name="verdict-exp3")
eid = g(exp, "id")

d = c.datasets.get_dataset(dataset=ds_id)
exs = g(d, "examples") or []
first = list(exs)[0]
ex_id = g(first, "id")

now = datetime.now(UTC)
c.experiments.log_run(
    experiment_id=eid,
    dataset_example_id=ex_id,
    output="claimed COMPLETED",
    start_time=now,
    end_time=now + timedelta(seconds=1),
)

info = c.experiments.get_experiment(experiment_id=eid)
runs = g(info, "task_runs") or []
rid = g(list(runs)[0], "id")
print("run id:", rid)


def show(tag: str) -> int:
    r = c.experiments.get_experiment(experiment_id=eid)
    evs = g(r, "evaluation_runs") or []
    pairs = [(g(e, "name"), g(e, "label")) for e in evs]
    print(f"{tag}: count={len(pairs)} -> {pairs}")
    return len(pairs)


for label in ["PASS", "FAIL", "UNKNOWN", "ERROR"]:
    c.experiments.log_evaluation(
        experiment_run_id=rid, name="ZM-R001", label=label, annotator_kind="CODE"
    )
show("same metric x4 labels")

c.experiments.log_evaluation(
    experiment_run_id=rid, name="ZM-R002", label="PASS", annotator_kind="CODE"
)
show("+ distinct metric ZM-R002")

c.experiments.log_evaluation(
    experiment_run_id=rid, name="ZM-R001", label="PASS", annotator_kind="CODE"
)
show("re-log ZM-R001")
