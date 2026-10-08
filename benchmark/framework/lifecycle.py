from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from framework.ids import utc_rfc3339
from framework.io_utils import (
    FrameworkError,
    append_log,
    atomic_write_json,
    read_json,
)


STATES = {
    "CREATED",
    "PREPARING",
    "READY",
    "RUNNING",
    "ANALYZING",
    "COMPLETE",
    "FAILED",
    "ABORTED",
}

ALLOWED_TRANSITIONS = {
    "CREATED": {"PREPARING"},
    "PREPARING": {"READY", "FAILED"},
    "READY": {"RUNNING", "ABORTED"},
    "RUNNING": {"ANALYZING", "FAILED", "ABORTED"},
    "ANALYZING": {"COMPLETE", "FAILED"},
    "FAILED": {"PREPARING", "RUNNING", "ANALYZING"},
    "ABORTED": {"RUNNING"},
    "COMPLETE": set(),
}


def initial_state(experiment_id: str) -> dict[str, Any]:
    now = utc_rfc3339()
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "state": "CREATED",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "failure": None,
        "runs": {
            "planned": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        },
    }


def load_state(experiment_dir: Path) -> dict[str, Any]:
    return read_json(experiment_dir / "state.json")


def transition(
    experiment_dir: Path,
    target: str,
    *,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if target not in STATES:
        raise FrameworkError(f"unknown lifecycle state: {target}")

    state_path = experiment_dir / "state.json"
    current = load_state(experiment_dir)
    source = current.get("state")

    if source not in STATES:
        raise FrameworkError(f"invalid current lifecycle state: {source!r}")

    if target not in ALLOWED_TRANSITIONS[source]:
        raise FrameworkError(f"illegal lifecycle transition: {source} -> {target}")

    updated = deepcopy(current)
    now = utc_rfc3339()
    updated["state"] = target
    updated["updated_at"] = now

    if target == "RUNNING" and updated.get("started_at") is None:
        updated["started_at"] = now

    if target == "COMPLETE":
        updated["completed_at"] = now
        updated["failure"] = None
    elif target == "FAILED":
        if not failure:
            raise FrameworkError("FAILED transition requires failure metadata")
        updated["failure"] = failure
    else:
        updated["failure"] = None

    atomic_write_json(state_path, updated)
    append_log(
        experiment_dir / "logs" / "framework.log",
        f"{now} lifecycle {source} -> {target}",
    )
    return updated


def update_run_counts(
    experiment_dir: Path,
    *,
    planned: int | None = None,
    completed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
) -> dict[str, Any]:
    state_path = experiment_dir / "state.json"
    state = load_state(experiment_dir)
    counts = dict(state.get("runs", {}))

    changes = {
        "planned": planned,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
    }

    for key, value in changes.items():
        if value is None:
            continue
        if value < 0:
            raise FrameworkError(f"run count {key} cannot be negative")
        counts[key] = value

    state["runs"] = counts
    state["updated_at"] = utc_rfc3339()
    atomic_write_json(state_path, state)
    return state
