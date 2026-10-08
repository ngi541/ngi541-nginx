#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = SCRIPT_DIR.parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from framework.ids import generate_experiment_id, utc_rfc3339, validate_slug
from framework.io_utils import (
    FrameworkError,
    append_log,
    atomic_write_json,
    read_json,
    write_immutable_json,
)
from framework.lifecycle import initial_state, transition, update_run_counts
from framework.schedule import build_schedule, resolve_common_request
from framework.validation import COMMON_DIRS, validate_experiment, validate_request


REPO_ROOT = SCRIPT_DIR.parents[1]
EXPERIMENTS_ROOT = REPO_ROOT / "experiments"


def parse_parameter(text: str) -> tuple[str, Any]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(
            "--param must use NAME=VALUE syntax"
        )

    name, raw = text.split("=", 1)
    name = name.strip()

    if not name:
        raise argparse.ArgumentTypeError("parameter name must not be empty")

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw

    return name, value


def experiment_dir(experiment_id: str) -> Path:
    return EXPERIMENTS_ROOT / experiment_id


def ensure_experiment_exists(experiment_id: str) -> Path:
    path = experiment_dir(experiment_id)
    if not path.is_dir():
        raise FrameworkError(f"experiment not found: {experiment_id}")
    return path


def command_create(args: argparse.Namespace) -> int:
    workload = validate_slug(args.workload, "workload")
    environment = validate_slug(args.environment, "environment")

    variants = [
        validate_slug(variant, "variant")
        for variant in args.variant
    ]

    parameters: dict[str, Any] = {}
    for name, value in args.param:
        if name in parameters:
            raise FrameworkError(f"duplicate parameter: {name}")
        parameters[name] = value

    if "repetitions" in parameters:
        raise FrameworkError(
            "use --repetitions instead of --param repetitions=..."
        )
    parameters["repetitions"] = args.repetitions

    comparison: dict[str, Any] = {}
    if args.comparison_mode is not None:
        comparison["mode"] = args.comparison_mode
    if args.random_seed is not None:
        comparison["random_seed"] = args.random_seed

    request: dict[str, Any] = {
        "workload": workload,
        "environment": environment,
        "variants": variants,
        "parameters": parameters,
    }

    if comparison:
        request["comparison"] = comparison

    if args.alias is not None:
        request["alias"] = args.alias

    validate_request(request)

    experiment_id = generate_experiment_id(workload, environment)
    path = experiment_dir(experiment_id)

    if path.exists():
        raise FrameworkError(
            f"refusing to overwrite existing experiment directory: {path}"
        )

    path.mkdir(parents=True)

    for rel in COMMON_DIRS:
        (path / rel).mkdir(parents=True, exist_ok=True)

    write_immutable_json(path / "config" / "request.json", request)
    atomic_write_json(path / "state.json", initial_state(experiment_id))

    append_log(
        path / "logs" / "framework.log",
        f"{utc_rfc3339()} experiment created id={experiment_id}",
    )

    transition(path, "PREPARING")

    print(experiment_id)
    print(path)
    return 0


def command_plan(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)

    request = read_json(path / "config" / "request.json")
    validate_request(request)

    resolved = resolve_common_request(request)
    schedule = build_schedule(args.experiment_id, resolved)

    write_immutable_json(
        path / "config" / "resolved.json",
        resolved,
    )
    write_immutable_json(
        path / "execution" / "schedule.json",
        schedule,
    )

    update_run_counts(path, planned=len(schedule["runs"]))

    append_log(
        path / "logs" / "framework.log",
        f"{utc_rfc3339()} execution plan generated "
        f"runs={len(schedule['runs'])} "
        f"mode={schedule['comparison_mode']}",
    )

    print(f"experiment: {args.experiment_id}")
    print(f"runs:       {len(schedule['runs'])}")
    print(f"mode:       {schedule['comparison_mode']}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)
    state = read_json(path / "state.json")

    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0

    runs = state.get("runs", {})
    print(f"experiment: {args.experiment_id}")
    print(f"state:      {state.get('state')}")
    print(
        "runs:       "
        f"planned={runs.get('planned', 0)} "
        f"completed={runs.get('completed', 0)} "
        f"failed={runs.get('failed', 0)} "
        f"skipped={runs.get('skipped', 0)}"
    )

    failure = state.get("failure")
    if failure:
        print(
            f"failure:    "
            f"{failure.get('stage')}: {failure.get('message')}"
        )

    return 0


def command_validate(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)
    errors = validate_experiment(path)

    if errors:
        print("FAIL: experiment validation", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"PASS: experiment validation: {args.experiment_id}")
    return 0


def command_attempt(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)
    schedule = read_json(path / "execution" / "schedule.json")

    run_ids = {run["run_id"] for run in schedule["runs"]}
    if args.run_id not in run_ids:
        raise FrameworkError(
            f"run id is not present in execution schedule: {args.run_id}"
        )

    run_dir = path / "raw" / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    existing = []
    for child in run_dir.iterdir():
        if child.is_dir() and child.name.startswith("attempt-"):
            try:
                existing.append(int(child.name.split("-", 1)[1]))
            except (IndexError, ValueError):
                continue

    next_number = max(existing, default=0) + 1
    attempt_dir = run_dir / f"attempt-{next_number:02d}"
    attempt_dir.mkdir()

    print(attempt_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="experiment",
        description="NGI541 portable experiment framework core",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create",
        help="create a new experiment and enter PREPARING state",
    )
    create.add_argument("--workload", required=True)
    create.add_argument("--environment", required=True)
    create.add_argument(
        "--variant",
        action="append",
        required=True,
        help="repeat for each variant",
    )
    create.add_argument(
        "--param",
        action="append",
        type=parse_parameter,
        default=[],
        metavar="NAME=VALUE",
        help=(
            "workload parameter; VALUE is parsed as JSON when possible "
            "(example: --param 'payload_bytes=[1024,16384]')"
        ),
    )
    create.add_argument(
        "--repetitions",
        type=int,
        default=1,
    )
    create.add_argument(
        "--comparison-mode",
        choices=["single", "fixed", "paired-balanced", "randomized"],
    )
    create.add_argument("--random-seed", type=int)
    create.add_argument("--alias")
    create.set_defaults(func=command_create)

    plan = subparsers.add_parser(
        "plan",
        help="resolve common configuration and generate immutable run schedule",
    )
    plan.add_argument("experiment_id")
    plan.set_defaults(func=command_plan)

    status = subparsers.add_parser(
        "status",
        help="show experiment lifecycle state",
    )
    status.add_argument("experiment_id")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    validate = subparsers.add_parser(
        "validate",
        help="validate the common experiment structure",
    )
    validate.add_argument("experiment_id")
    validate.set_defaults(func=command_validate)

    attempt = subparsers.add_parser(
        "allocate-attempt",
        help="allocate a new append-only attempt directory for a scheduled run",
    )
    attempt.add_argument("experiment_id")
    attempt.add_argument("run_id")
    attempt.set_defaults(func=command_attempt)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "repetitions", 1) < 1:
        parser.error("--repetitions must be >= 1")

    try:
        return args.func(args)
    except (FrameworkError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
