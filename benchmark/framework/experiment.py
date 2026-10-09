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

from framework.analysis import analyze_experiment, validate_analysis_outputs
from framework.environment import prepare_environment
from framework.ids import (
    generate_experiment_id,
    utc_rfc3339,
    validate_slug,
)
from framework.io_utils import (
    FrameworkError,
    append_log,
    atomic_write_json,
    atomic_write_text,
    read_json,
    write_immutable_json,
)
from framework.lifecycle import (
    initial_state,
    load_state,
    transition,
    update_run_counts,
)
from framework.manifest import build_manifest
from framework.provenance import (
    discover_dependencies,
    discover_sources,
    record_binaries,
    record_build,
    record_runtime_bindings,
    run_preflight,
)
from framework.readme import generate_prepared_readme
from framework.schedule import build_schedule, resolve_common_request
from framework.validation import (
    COMMON_DIRS,
    validate_experiment,
    validate_request,
)
from framework.workloads import (
    execute_workload,
    prepare_workload,
    resolve_workload_config,
)


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
    state = load_state(path)

    if state["state"] != "PREPARING":
        raise FrameworkError(
            "plan requires PREPARING state; "
            f"current state is {state['state']}"
        )

    request = read_json(path / "config" / "request.json")
    validate_request(request)

    resolved = resolve_common_request(request)
    resolved = resolve_workload_config(request, resolved)
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


def _ensure_preparing(path: Path) -> None:
    state = load_state(path)

    if state["state"] == "FAILED":
        if state.get("failure", {}).get("stage") != "preparing":
            raise FrameworkError(
                "prepare can resume only a FAILED preparation; "
                "this experiment failed during another stage"
            )
        transition(path, "PREPARING")
        return

    if state["state"] != "PREPARING":
        raise FrameworkError(
            "prepare requires PREPARING or preparation-FAILED state; "
            f"current state is {state['state']}"
        )


def command_prepare(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)
    _ensure_preparing(path)

    if not (path / "config" / "resolved.json").is_file():
        raise FrameworkError(
            "experiment must be planned before prepare"
        )

    if not (path / "execution" / "schedule.json").is_file():
        raise FrameworkError(
            "execution schedule is missing; run plan first"
        )

    request = read_json(path / "config" / "request.json")
    resolved = read_json(path / "config" / "resolved.json")

    try:
        adapter = prepare_environment(
            path,
            request["environment"],
        )

        sources = discover_sources(
            REPO_ROOT,
            args.source,
        )
        dependencies = discover_dependencies(REPO_ROOT)

        binaries = record_binaries(
            REPO_ROOT,
            args.binary,
            path / "provenance" / "binaries.sha256",
        )

        runtime_bindings = record_runtime_bindings(
            REPO_ROOT,
            resolved["variants"],
            binaries,
            args.runtime_library,
        )

        atomic_write_json(
            path / "provenance" / "runtime-bindings.json",
            runtime_bindings,
        )

        build = record_build(
            binaries,
            runtime_bindings,
        )

        atomic_write_json(
            path / "provenance" / "sources.json",
            sources,
        )
        atomic_write_json(
            path / "provenance" / "dependencies.json",
            dependencies,
        )
        atomic_write_json(
            path / "provenance" / "build.json",
            build,
        )

        prepare_workload(
            path,
            resolved,
            dependencies,
            runtime_bindings,
        )

        preflight = run_preflight(
            path,
            REPO_ROOT,
            args.preflight,
        )

        atomic_write_json(
            path / "provenance" / "preflight.json",
            preflight,
        )

        if not preflight["passed"]:
            raise FrameworkError(
                "one or more preparation preflight checks failed"
            )

    except Exception as exc:
        state = load_state(path)
        if state["state"] == "PREPARING":
            transition(
                path,
                "FAILED",
                failure={
                    "stage": "preparing",
                    "message": str(exc),
                    "run_id": None,
                },
            )
        raise

    append_log(
        path / "logs" / "framework.log",
        f"{utc_rfc3339()} preparation artifacts collected "
        f"adapter={adapter['adapter']} "
        f"sources={len(sources['sources'])} "
        f"binaries={len(binaries['artifacts'])}",
    )

    print(f"experiment: {args.experiment_id}")
    print(f"environment: {adapter['adapter']}")
    print(f"sources:     {len(sources['sources'])}")
    print(f"binaries:    {len(binaries['artifacts'])}")
    print("workload:    PASS")
    print("preflight:   PASS")
    print("state:       PREPARING")
    return 0


def command_seal(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)
    state = load_state(path)

    if state["state"] != "PREPARING":
        raise FrameworkError(
            "seal requires PREPARING state; "
            f"current state is {state['state']}"
        )

    required = (
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

    missing = [
        rel
        for rel in required
        if not (path / rel).is_file()
    ]
    if missing:
        raise FrameworkError(
            "cannot seal experiment; missing preparation artifacts: "
            + ", ".join(missing)
        )

    preflight = read_json(path / "provenance" / "preflight.json")
    workload_preflight = read_json(
        path / "execution" / "workload" / "preflight.json"
    )

    if not preflight.get("passed"):
        raise FrameworkError(
            "cannot seal experiment with failed generic preflight"
        )
    if not workload_preflight.get("passed"):
        raise FrameworkError(
            "cannot seal experiment with failed workload preflight"
        )

    manifest = build_manifest(path)
    write_immutable_json(path / "manifest.json", manifest)

    transition(path, "READY")

    atomic_write_text(
        path / "README.md",
        generate_prepared_readme(path),
    )

    errors = validate_experiment(path)
    if errors:
        raise FrameworkError(
            "sealed experiment failed validation: "
            + "; ".join(errors)
        )

    append_log(
        path / "logs" / "framework.log",
        f"{utc_rfc3339()} manifest sealed; experiment READY",
    )

    print(f"experiment: {args.experiment_id}")
    print("state:      READY")
    print("manifest:   manifest.json")
    return 0


def command_execute(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)

    try:
        execute_workload(path)
    except KeyboardInterrupt:
        print("ABORTED: execution interrupted", file=sys.stderr)
        return 130

    state = load_state(path)
    print(f"experiment: {args.experiment_id}")
    print(f"state:      {state['state']}")
    print(
        "runs:       "
        f"planned={state['runs']['planned']} "
        f"completed={state['runs']['completed']} "
        f"failed={state['runs']['failed']} "
        f"skipped={state['runs']['skipped']}"
    )
    return 0


def command_analyze(args: argparse.Namespace) -> int:
    path = ensure_experiment_exists(args.experiment_id)
    state = load_state(path)

    if state["state"] == "FAILED":
        if state.get("failure", {}).get("stage") != "analyzing":
            raise FrameworkError(
                "analyze can resume only a FAILED analysis; "
                "this experiment failed during another stage"
            )
        transition(path, "ANALYZING")
    elif state["state"] != "ANALYZING":
        raise FrameworkError(
            "analyze requires ANALYZING or analysis-FAILED state; "
            f"current state is {state['state']}"
        )

    try:
        result = analyze_experiment(path)

        errors = validate_analysis_outputs(path)
        if errors:
            raise FrameworkError(
                "generated analysis outputs failed validation: "
                + "; ".join(errors)
            )

        common_errors = validate_experiment(path)
        if common_errors:
            raise FrameworkError(
                "experiment failed validation before completion: "
                + "; ".join(common_errors)
            )

        transition(path, "COMPLETE")

        final_errors = validate_experiment(path)
        if final_errors:
            raise FrameworkError(
                "completed experiment failed validation: "
                + "; ".join(final_errors)
            )

    except Exception as exc:
        current = load_state(path)
        if current["state"] == "ANALYZING":
            transition(
                path,
                "FAILED",
                failure={
                    "stage": "analyzing",
                    "message": str(exc),
                    "run_id": None,
                },
            )
        raise

    append_log(
        path / "logs" / "framework.log",
        f"{utc_rfc3339()} deterministic analysis complete "
        f"selected_runs={result['selected_runs']} "
        f"conditions={result['conditions']} pairs={result['pairs']}",
    )

    print(f"experiment: {args.experiment_id}")
    print("state:      COMPLETE")
    print(f"runs:       analyzed={result['selected_runs']}")
    print(f"conditions: {result['conditions']}")
    print(f"pairs:      {result['pairs']}")
    print("results:    processed/statistics.json")
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
    state = load_state(path)

    if state["state"] not in {"READY", "RUNNING"}:
        raise FrameworkError(
            "attempt allocation requires READY or RUNNING state; "
            f"current state is {state['state']}"
        )

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
    create.add_argument("--repetitions", type=int, default=1)
    create.add_argument(
        "--comparison-mode",
        choices=["single", "fixed", "paired-balanced", "randomized"],
    )
    create.add_argument("--random-seed", type=int)
    create.add_argument("--alias")
    create.set_defaults(func=command_create)

    plan = subparsers.add_parser(
        "plan",
        help="resolve workload configuration and generate immutable schedule",
    )
    plan.add_argument("experiment_id")
    plan.set_defaults(func=command_plan)

    prepare = subparsers.add_parser(
        "prepare",
        help="collect environment/provenance and prepare workload inputs",
    )
    prepare.add_argument("experiment_id")
    prepare.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="additional Git source to record",
    )
    prepare.add_argument(
        "--binary",
        action="append",
        default=[],
        metavar="VARIANT=PATH",
        help=(
            "runtime executable for a variant; every experiment variant "
            "must have exactly one binding"
        ),
    )
    prepare.add_argument(
        "--runtime-library",
        action="append",
        default=[],
        metavar="VARIANT=PATH",
        help=(
            "runtime shared library for a variant; repeat when several "
            "library files must be staged"
        ),
    )
    prepare.add_argument(
        "--preflight",
        action="append",
        default=[],
        metavar="NAME=COMMAND",
        help="additional preparation/preflight command",
    )
    prepare.set_defaults(func=command_prepare)

    seal = subparsers.add_parser(
        "seal",
        help="create immutable manifest and transition PREPARING -> READY",
    )
    seal.add_argument("experiment_id")
    seal.set_defaults(func=command_seal)

    execute = subparsers.add_parser(
        "execute",
        help="execute or resume the immutable workload schedule",
    )
    execute.add_argument("experiment_id")
    execute.set_defaults(func=command_execute)

    analyze = subparsers.add_parser(
        "analyze",
        help="analyze frozen raw measurements and complete the experiment",
    )
    analyze.add_argument("experiment_id")
    analyze.set_defaults(func=command_analyze)

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
