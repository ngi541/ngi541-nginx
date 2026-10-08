from __future__ import annotations

from pathlib import Path
from typing import Any

from framework.io_utils import FrameworkError
from workloads.http3.adapter import (
    execute_http3_schedule,
    prepare_http3_workload,
    resolve_http3_config,
)


def resolve_workload_config(
    request: dict[str, Any],
    resolved: dict[str, Any],
) -> dict[str, Any]:
    workload = request["workload"]

    if workload == "http3":
        return resolve_http3_config(request, resolved)

    raise FrameworkError(f"workload adapter is not implemented yet: {workload}")


def prepare_workload(
    experiment_dir: Path,
    resolved: dict[str, Any],
    dependencies: dict[str, Any],
    runtime_bindings: dict[str, Any],
) -> dict[str, Any]:
    workload = resolved["workload"]

    if workload == "http3":
        return prepare_http3_workload(
            experiment_dir,
            resolved,
            dependencies,
            runtime_bindings,
        )

    raise FrameworkError(f"workload adapter is not implemented yet: {workload}")


def execute_workload(
    experiment_dir: Path,
) -> None:
    resolved_path = experiment_dir / "config" / "resolved.json"

    from framework.io_utils import read_json

    resolved = read_json(resolved_path)
    workload = resolved["workload"]

    if workload == "http3":
        execute_http3_schedule(experiment_dir)
        return

    raise FrameworkError(f"workload adapter is not implemented yet: {workload}")
