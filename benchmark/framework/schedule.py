from __future__ import annotations

import itertools
import random
from typing import Any

from framework.io_utils import FrameworkError


SUPPORTED_COMPARISON_MODES = {
    "single",
    "fixed",
    "paired-balanced",
    "randomized",
}


def resolve_common_request(request: dict[str, Any]) -> dict[str, Any]:
    variants = request.get("variants")
    parameters = dict(request.get("parameters") or {})

    if not isinstance(variants, list) or not variants:
        raise FrameworkError("request must contain at least one variant")

    if len(set(variants)) != len(variants):
        raise FrameworkError("request variants must be unique")

    repetitions = parameters.get("repetitions", 1)
    if not isinstance(repetitions, int) or repetitions < 1:
        raise FrameworkError("parameters.repetitions must be a positive integer")

    requested_mode = (request.get("comparison") or {}).get("mode")

    if requested_mode is None:
        if len(variants) == 1:
            comparison_mode = "single"
        elif len(variants) == 2:
            comparison_mode = "paired-balanced"
        else:
            comparison_mode = "fixed"
    else:
        comparison_mode = requested_mode

    if comparison_mode not in SUPPORTED_COMPARISON_MODES:
        raise FrameworkError(f"unsupported comparison mode: {comparison_mode}")

    if comparison_mode == "single" and len(variants) != 1:
        raise FrameworkError("single comparison mode requires exactly one variant")

    if comparison_mode == "paired-balanced" and len(variants) != 2:
        raise FrameworkError(
            "paired-balanced comparison mode requires exactly two variants"
        )

    random_seed = (request.get("comparison") or {}).get("random_seed")
    if comparison_mode == "randomized":
        if random_seed is None:
            random_seed = 0
        if not isinstance(random_seed, int):
            raise FrameworkError("comparison.random_seed must be an integer")

    resolved = {
        "workload": request["workload"],
        "environment": request["environment"],
        "variants": list(variants),
        "parameters": parameters,
        "comparison": {
            "mode": comparison_mode,
            "random_seed": random_seed if comparison_mode == "randomized" else None,
        },
    }

    if request.get("alias") is not None:
        resolved["alias"] = request["alias"]

    if request.get("conditions") is not None:
        resolved["conditions"] = [
            dict(condition)
            for condition in request["conditions"]
        ]

    return resolved


def _parameter_matrix(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    axis_names: list[str] = []
    axis_values: list[list[Any]] = []
    fixed: dict[str, Any] = {}

    for name in sorted(parameters):
        if name == "repetitions":
            continue

        value = parameters[name]
        if isinstance(value, list):
            if not value:
                raise FrameworkError(f"parameter axis {name!r} must not be empty")
            axis_names.append(name)
            axis_values.append(value)
        else:
            fixed[name] = value

    if not axis_names:
        return [fixed]

    rows = []
    for values in itertools.product(*axis_values):
        row = dict(fixed)
        for name, value in zip(axis_names, values):
            row[name] = value
        rows.append(row)

    return rows


def build_schedule(
    experiment_id: str,
    resolved: dict[str, Any],
) -> dict[str, Any]:
    variants = resolved["variants"]
    parameters = resolved["parameters"]
    repetitions = parameters.get("repetitions", 1)
    mode = resolved["comparison"]["mode"]
    random_seed = resolved["comparison"].get("random_seed")

    explicit_conditions = resolved.get("conditions")
    if explicit_conditions is not None:
        fixed = {
            name: value
            for name, value in parameters.items()
            if name != "repetitions"
        }
        matrix = []
        for condition in explicit_conditions:
            row = dict(fixed)
            row.update(condition)
            matrix.append(row)
    else:
        matrix = _parameter_matrix(parameters)

    rng = random.Random(random_seed)

    runs: list[dict[str, Any]] = []
    sequence = 0
    pair_sequence = 0

    for parameter_set in matrix:
        for repetition in range(1, repetitions + 1):
            pair_sequence += 1

            if mode == "single":
                order = list(variants)
                pair_id = None
            elif mode == "paired-balanced":
                order = list(variants)
                if pair_sequence % 2 == 0:
                    order.reverse()
                pair_id = f"pair-{pair_sequence:04d}"
            elif mode == "randomized":
                order = list(variants)
                rng.shuffle(order)
                pair_id = (
                    f"pair-{pair_sequence:04d}"
                    if len(order) > 1 else None
                )
            else:
                order = list(variants)
                pair_id = (
                    f"pair-{pair_sequence:04d}"
                    if len(order) > 1 else None
                )

            for variant in order:
                sequence += 1
                runs.append(
                    {
                        "sequence": sequence,
                        "run_id": f"run-{sequence:04d}",
                        "pair_id": pair_id,
                        "variant": variant,
                        "repetition": repetition,
                        "parameters": dict(parameter_set),
                    }
                )

    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "comparison_mode": mode,
        "random_seed": random_seed if mode == "randomized" else None,
        "runs": runs,
    }
