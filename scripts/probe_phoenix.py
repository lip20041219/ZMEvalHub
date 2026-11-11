"""Probe Phoenix 21.0.0 real capabilities: datasets, experiments, spans.

Run against a live local server:
    PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006 uv run python probe_phoenix.py
"""

from __future__ import annotations

import os
import uuid

ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = ENDPOINT
os.environ.setdefault("PHOENIX_CLIENT_HEADERS", "")

from phoenix.client import Client  # noqa: E402

client = Client(base_url=ENDPOINT)
tag = uuid.uuid4().hex[:8]


def report(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _get(obj, key):
    """Phoenix 21.0.0 sometimes returns dicts, sometimes pydantic models."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


# ---------------------------------------------------------------- datasets
print("\n=== 1. DATASET ===")
ds_name = f"zmeval-probe-{tag}"
ds = client.datasets.create_dataset(
    name=ds_name,
    dataframe=None,
    examples=[
        {
            "input": {"task": "fix failing test"},
            "output": {"requires_post_edit_test": True},
            "metadata": {"case_id": "case-1", "kind": "coding_agent"},
        }
    ],
)
report("dataset created", bool(ds.id), f"id={ds.id}")

# read back
ds2 = client.datasets.get_dataset(dataset=ds.id)
examples = list(ds2.examples)
report("dataset read back", len(examples) == 1, f"examples={len(examples)}")
if examples:
    ex = examples[0]
    # examples come back as dicts in 21.0.0
    d = ex if isinstance(ex, dict) else ex.__dict__
    inp = d.get("input", {})
    meta = d.get("metadata", {})
    report(
        "example roundtrip",
        inp.get("task") == "fix failing test" and meta.get("case_id") == "case-1",
        f"keys={list(d.keys())}",
    )

# versioning: is there a dataset version concept?
report(
    "dataset has version attr",
    hasattr(ds2, "version") or hasattr(ds2, "version_id"),
    f"attrs={[a for a in dir(ds2) if 'version' in a.lower()]}",
)

# idempotency: same name twice
try:
    ds_dup = client.datasets.create_dataset(name=ds_name, dataframe=None, examples=[])
    report(
        "duplicate name creates NEW dataset (not idempotent)",
        ds_dup.id != ds.id,
        f"first={ds.id} second={ds_dup.id}",
    )
except Exception as e:
    report("duplicate name rejected", True, f"{type(e).__name__}: {str(e)[:120]}")

# ------------------------------------------------------------- experiments
print("\n=== 2. EXPERIMENT ===")
try:
    exp = client.experiments.create(
        dataset_id=ds.id,
        experiment_name=f"zmeval-exp-{tag}",
        experiment_metadata={"subject": "ZMAI", "git_sha": None, "trace_complete": False},
        repetitions=2,
    )
    exp_id = _get(exp, "id")
    report("experiment created", bool(exp_id), f"id={exp_id} type={type(exp).__name__}")
    exp_read = client.experiments.get_experiment(experiment_id=exp_id)
    # NOTE: get_experiment() names the key experiment_id, while create() uses id.
    read_id = _get(exp_read, "experiment_id") or _get(exp_read, "id")
    report("experiment read back", read_id == exp_id, f"read={read_id}")
    meta = _get(exp_read, "experiment_metadata") or _get(exp_read, "metadata") or {}
    report("experiment metadata persisted", meta.get("subject") == "ZMAI", f"meta={meta}")
    report(
        "experiment pins dataset_version_id",
        bool(_get(exp_read, "dataset_version_id")),
        f"version={_get(exp_read, 'dataset_version_id')}",
    )
except Exception as e:
    report("experiment create", False, f"{type(e).__name__}: {str(e)[:200]}")

# ------------------------------------------------------ dataset versioning
print("\n=== 3. DATASET VERSIONING ===")
versions = client.datasets.get_dataset_versions(dataset=ds.id)
report("dataset versions listed", len(versions) >= 1, f"count={len(versions)}")

# does adding examples create a new version?
client.datasets.add_examples_to_dataset(
    dataset=ds.id,
    inputs=[{"task": "second task"}],
)
versions_after = client.datasets.get_dataset_versions(dataset=ds.id)
report(
    "mutation creates NEW version (immutability)",
    len(versions_after) > len(versions),
    f"before={len(versions)} after={len(versions_after)}",
)

# can we pin an experiment to an older version?
try:
    exp_v1 = client.experiments.create(
        dataset_id=ds.id,
        dataset_version_id=_get(versions[0], "id"),
        experiment_name=f"zmeval-exp-v1-{tag}",
    )
    report(
        "experiment can pin dataset_version_id",
        bool(_get(exp_v1, "id")),
        f"pinned={_get(versions[0], 'id')}",
    )
except Exception as e:
    report("experiment pin version", False, f"{type(e).__name__}: {str(e)[:160]}")

print("\n=== DONE ===")
