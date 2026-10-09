from __future__ import annotations

from pathlib import Path
from typing import Any

from framework.analysis import validate_analysis_outputs
from framework.ids import (
    EXPERIMENT_ID_RE,
    PAIR_ID_RE,
    RUN_ID_RE,
    SLUG_RE,
)
from framework.io_utils import FrameworkError, read_json


COMMON_DIRS = (
    "config",
    "environment",
    "environment/nodes",
    "provenance",
    "execution",
    "raw",
    "raw/runs",
    "processed",
    "figures",
    "logs",
)

SEALED_STATES = {
    "READY",
    "RUNNING",
    "ANALYZING",
    "COMPLETE",
    "ABORTED",
}


def validate_request(request: dict[str, Any]) -> None:
    required = {"workload", "environment", "variants", "parameters"}
    missing = required.difference(request)
    if missing:
        raise FrameworkError(
            f"request is missing required fields: {', '.join(sorted(missing))}"
        )

    if not SLUG_RE.fullmatch(str(request["workload"])):
        raise FrameworkError("invalid workload identifier")

    if not SLUG_RE.fullmatch(str(request["environment"])):
        raise FrameworkError("invalid environment identifier")

    variants = request["variants"]
    if not isinstance(variants, list) or not variants:
        raise FrameworkError("variants must be a non-empty array")

    for variant in variants:
        if not isinstance(variant, str) or not SLUG_RE.fullmatch(variant):
            raise FrameworkError(f"invalid variant identifier: {variant!r}")

    if not isinstance(request["parameters"], dict):
        raise FrameworkError("parameters must be an object")


def _validate_schedule(
    schedule: dict[str, Any],
    experiment_id: str,
    errors: list[str],
) -> None:
    if schedule.get("experiment_id") != experiment_id:
        errors.append(
            "schedule.json experiment_id does not match directory name"
        )

    runs = schedule.get("runs")
    if not isinstance(runs, list) or not runs:
        errors.append("schedule.json runs must be a non-empty array")
        return

    seen_run_ids: set[str] = set()
    expected_sequence = 1

    for run in runs:
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            errors.append(f"invalid run_id: {run_id!r}")
        elif run_id in seen_run_ids:
            errors.append(f"duplicate run_id: {run_id}")
        else:
            seen_run_ids.add(run_id)

        if run.get("sequence") != expected_sequence:
            errors.append(
                f"unexpected sequence for {run_id}: "
                f"expected {expected_sequence}, got {run.get('sequence')}"
            )
        expected_sequence += 1

        pair_id = run.get("pair_id")
        if pair_id is not None and (
            not isinstance(pair_id, str)
            or not PAIR_ID_RE.fullmatch(pair_id)
        ):
            errors.append(f"invalid pair_id: {pair_id!r}")


def validate_experiment(experiment_dir: Path) -> list[str]:
    errors: list[str] = []
    experiment_id = experiment_dir.name

    if not EXPERIMENT_ID_RE.fullmatch(experiment_id):
        errors.append(f"invalid experiment directory name: {experiment_id}")

    for rel in COMMON_DIRS:
        if not (experiment_dir / rel).is_dir():
            errors.append(f"missing directory: {rel}")

    try:
        request = read_json(experiment_dir / "config" / "request.json")
        validate_request(request)
    except FrameworkError as exc:
        errors.append(str(exc))

    state = None
    try:
        state = read_json(experiment_dir / "state.json")
        if state.get("experiment_id") != experiment_id:
            errors.append(
                "state.json experiment_id does not match directory name"
            )
        if state.get("schema_version") != 1:
            errors.append("state.json schema_version must be 1")
    except FrameworkError as exc:
        errors.append(str(exc))

    schedule_path = experiment_dir / "execution" / "schedule.json"
    if schedule_path.exists():
        try:
            _validate_schedule(
                read_json(schedule_path),
                experiment_id,
                errors,
            )
        except FrameworkError as exc:
            errors.append(str(exc))

    if state and state.get("state") in SEALED_STATES:
        required_files = (
            "manifest.json",
            "config/resolved.json",
            "environment/adapter.json",
            "provenance/sources.json",
            "provenance/dependencies.json",
            "provenance/build.json",
            "provenance/binaries.sha256",
            "provenance/runtime-bindings.json",
            "provenance/preflight.json",
            "execution/schedule.json",
            "execution/workload/manifest.json",
            "execution/workload/preflight.json",
        )

        for rel in required_files:
            if not (experiment_dir / rel).is_file():
                errors.append(f"sealed experiment missing file: {rel}")

        for preflight_rel in (
            "provenance/preflight.json",
            "execution/workload/preflight.json",
        ):
            path = experiment_dir / preflight_rel
            if path.is_file():
                try:
                    preflight = read_json(path)
                    if not preflight.get("passed"):
                        errors.append(
                            f"sealed experiment has non-passing {preflight_rel}"
                        )
                except FrameworkError as exc:
                    errors.append(str(exc))

        manifest_path = experiment_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = read_json(manifest_path)
                if (
                    manifest.get("experiment", {}).get("id")
                    != experiment_id
                ):
                    errors.append(
                        "manifest.json experiment id does not match directory"
                    )
            except FrameworkError as exc:
                errors.append(str(exc))

    if state and state.get("state") in {"ANALYZING", "COMPLETE"}:
        schedule = None
        try:
            schedule = read_json(
                experiment_dir / "execution" / "schedule.json"
            )
        except FrameworkError as exc:
            errors.append(str(exc))

        if schedule:
            for run in schedule["runs"]:
                run_dir = (
                    experiment_dir
                    / "raw"
                    / "runs"
                    / run["run_id"]
                )
                valid = False

                if run_dir.is_dir():
                    for measurement_path in run_dir.glob(
                        "attempt-*/measurement.json"
                    ):
                        try:
                            measurement = read_json(measurement_path)
                            if measurement.get(
                                "execution", {}
                            ).get("valid") is True:
                                valid = True
                                break
                        except FrameworkError:
                            pass

                if not valid:
                    errors.append(
                        f"completed execution missing valid measurement: "
                        f"{run['run_id']}"
                    )

    if state and state.get("state") == "COMPLETE":
        errors.extend(validate_analysis_outputs(experiment_dir))

    return errors
