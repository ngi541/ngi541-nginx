from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

from framework.io_utils import (
    FrameworkError,
    atomic_write_json,
    atomic_write_text,
    read_json,
)
from framework.provenance import git_source_info, sha256_file


PRIMARY_METRIC = "requests_per_second"
ANALYSIS_SCHEMA_VERSION = 1


def _attempt_number(path: Path) -> int:
    name = path.parent.name
    if not name.startswith("attempt-"):
        raise FrameworkError(f"invalid attempt directory: {path.parent}")
    try:
        number = int(name.split("-", 1)[1])
    except (IndexError, ValueError) as exc:
        raise FrameworkError(f"invalid attempt directory: {path.parent}") from exc
    if number < 1:
        raise FrameworkError(f"invalid attempt number: {number}")
    return number


def _measurement_paths(experiment_dir: Path, run_id: str) -> list[Path]:
    run_dir = experiment_dir / "raw" / "runs" / run_id
    paths = list(run_dir.glob("attempt-*/measurement.json")) if run_dir.is_dir() else []
    return sorted(paths, key=_attempt_number)


def _first_valid_measurement(
    experiment_dir: Path,
    scheduled_run: dict[str, Any],
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    paths = _measurement_paths(experiment_dir, scheduled_run["run_id"])
    if not paths:
        raise FrameworkError(
            f"analysis missing measurements for {scheduled_run['run_id']}"
        )

    selected: tuple[dict[str, Any], Path] | None = None
    earlier_invalid = 0

    for path in paths:
        measurement = read_json(path)
        if measurement.get("execution", {}).get("valid") is True:
            selected = (measurement, path)
            break
        earlier_invalid += 1

    if selected is None:
        raise FrameworkError(
            f"analysis found no valid attempt for {scheduled_run['run_id']}"
        )

    measurement, path = selected
    attempt_number = _attempt_number(path)
    _validate_selected_measurement(measurement, scheduled_run, attempt_number)

    later_attempts = sum(
        1 for candidate in paths if _attempt_number(candidate) > attempt_number
    )

    selection = {
        "run_id": scheduled_run["run_id"],
        "selected_attempt": attempt_number,
        "selected_path": str(path.relative_to(experiment_dir)),
        "earlier_invalid_attempts": earlier_invalid,
        "later_attempts_ignored": later_attempts,
        "rule": "first-valid-attempt-by-attempt-number",
    }
    return measurement, path, selection


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrameworkError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise FrameworkError(f"{name} must be finite")
    return result


def _validate_selected_measurement(
    measurement: dict[str, Any],
    scheduled_run: dict[str, Any],
    attempt_number: int,
) -> None:
    run_id = scheduled_run["run_id"]

    if measurement.get("run_id") != run_id:
        raise FrameworkError(f"measurement run_id mismatch for {run_id}")
    if measurement.get("variant") != scheduled_run["variant"]:
        raise FrameworkError(f"measurement variant mismatch for {run_id}")
    if measurement.get("pair_id") != scheduled_run.get("pair_id"):
        raise FrameworkError(f"measurement pair_id mismatch for {run_id}")
    if measurement.get("attempt") != attempt_number:
        raise FrameworkError(f"measurement attempt mismatch for {run_id}")
    if measurement.get("execution", {}).get("valid") is not True:
        raise FrameworkError(f"selected measurement is not valid for {run_id}")
    if measurement.get("execution", {}).get("exit_code") != 0:
        raise FrameworkError(f"valid measurement has non-zero exit code for {run_id}")
    if measurement.get("observations", {}).get("completed_count_known") is not True:
        raise FrameworkError(f"completed request count is unknown for {run_id}")

    requests = measurement.get("requests", {})
    planned = requests.get("planned")
    completed = requests.get("completed")
    if not isinstance(planned, int) or planned <= 0:
        raise FrameworkError(f"invalid planned request count for {run_id}")
    if completed != planned:
        raise FrameworkError(f"incomplete valid measurement for {run_id}")

    elapsed_ns = measurement.get("timing", {}).get("elapsed_ns")
    if not isinstance(elapsed_ns, int) or elapsed_ns <= 0:
        raise FrameworkError(f"invalid elapsed_ns for {run_id}")

    metric = _finite_number(
        measurement.get("metrics", {}).get(PRIMARY_METRIC),
        f"{run_id}.{PRIMARY_METRIC}",
    )
    if metric <= 0:
        raise FrameworkError(f"{run_id}.{PRIMARY_METRIC} must be > 0")


def _condition_key(parameters: dict[str, Any]) -> str:
    return json.dumps(
        parameters,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _condition_catalog(schedule: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    order: list[str] = []
    catalog: dict[str, dict[str, Any]] = {}
    for run in schedule["runs"]:
        parameters = dict(run.get("parameters") or {})
        key = _condition_key(parameters)
        if key not in catalog:
            condition_id = f"condition-{len(order) + 1:04d}"
            order.append(key)
            catalog[key] = {
                "condition_id": condition_id,
                "parameters": parameters,
            }
    return order, catalog


def _sample_stddev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def _variant_statistics(values: list[float]) -> dict[str, Any]:
    if not values:
        raise FrameworkError("cannot summarize empty metric series")
    mean = statistics.fmean(values)
    stddev = _sample_stddev(values)
    cv = None
    if stddev is not None and mean != 0:
        cv = stddev / mean * 100.0
    return {
        "n": len(values),
        "mean": mean,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "sample_standard_deviation": stddev,
        "coefficient_of_variation_percent": cv,
    }


def _paired_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [float(row["delta_percent"]) for row in rows]
    ratios = [float(row["ratio"]) for row in rows]
    if not deltas:
        return {
            "n_pairs": 0,
            "mean_delta_percent": None,
            "median_delta_percent": None,
            "min_delta_percent": None,
            "max_delta_percent": None,
            "sample_standard_deviation_percent": None,
            "geometric_mean_ratio": None,
            "geometric_mean_delta_percent": None,
            "wins": 0,
            "losses": 0,
            "ties": 0,
        }

    geomean_ratio = None
    if all(ratio > 0 for ratio in ratios):
        geomean_ratio = math.exp(statistics.fmean(math.log(r) for r in ratios))

    return {
        "n_pairs": len(rows),
        "mean_delta_percent": statistics.fmean(deltas),
        "median_delta_percent": statistics.median(deltas),
        "min_delta_percent": min(deltas),
        "max_delta_percent": max(deltas),
        "sample_standard_deviation_percent": _sample_stddev(deltas),
        "geometric_mean_ratio": geomean_ratio,
        "geometric_mean_delta_percent": (
            (geomean_ratio - 1.0) * 100.0 if geomean_ratio is not None else None
        ),
        "wins": sum(1 for row in rows if row["winner"] == "candidate"),
        "losses": sum(1 for row in rows if row["winner"] == "baseline"),
        "ties": sum(1 for row in rows if row["winner"] == "tie"),
    }


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _csv_text(fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({name: _csv_value(row.get(name)) for name in fieldnames})
    return buffer.getvalue()


def _parameter_names(schedule: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    for run in schedule["runs"]:
        names.update((run.get("parameters") or {}).keys())
    return sorted(names)


def _normalize_runs(
    experiment_dir: Path,
    schedule: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []

    for run in schedule["runs"]:
        measurement, _, selection = _first_valid_measurement(
            experiment_dir,
            run,
        )
        selections.append(selection)
        metric = float(measurement["metrics"][PRIMARY_METRIC])
        row: dict[str, Any] = {
            "experiment_id": experiment_dir.name,
            "sequence": run["sequence"],
            "run_id": run["run_id"],
            "pair_id": run.get("pair_id"),
            "variant": run["variant"],
            "repetition": run.get("repetition"),
            "attempt": measurement["attempt"],
            "planned_requests": measurement["requests"]["planned"],
            "completed_requests": measurement["requests"]["completed"],
            "elapsed_ns": measurement["timing"]["elapsed_ns"],
            PRIMARY_METRIC: metric,
        }
        row.update(run.get("parameters") or {})
        rows.append(row)

    return rows, selections


def _build_variant_summary(
    rows: list[dict[str, Any]],
    condition_order: list[str],
    condition_catalog: dict[str, dict[str, Any]],
    variants: list[str],
    parameter_names: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        parameters = {name: row[name] for name in parameter_names}
        grouped[(_condition_key(parameters), row["variant"])].append(
            float(row[PRIMARY_METRIC])
        )

    csv_rows: list[dict[str, Any]] = []
    json_conditions: dict[str, Any] = {}
    for key in condition_order:
        condition = condition_catalog[key]
        condition_id = condition["condition_id"]
        json_conditions[condition_id] = {
            "parameters": condition["parameters"],
            "variants": {},
        }
        for variant in variants:
            values = grouped.get((key, variant), [])
            if not values:
                continue
            stats = _variant_statistics(values)
            json_conditions[condition_id]["variants"][variant] = stats
            csv_row = {
                "condition_id": condition_id,
                **condition["parameters"],
                "variant": variant,
                **stats,
            }
            csv_rows.append(csv_row)
    return csv_rows, json_conditions


def _build_pairs(
    rows: list[dict[str, Any]],
    schedule: dict[str, Any],
    condition_catalog: dict[str, dict[str, Any]],
    variants: list[str],
    parameter_names: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if schedule.get("comparison_mode") != "paired-balanced" or len(variants) != 2:
        return [], {}

    baseline, candidate = variants
    by_pair: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        pair_id = row.get("pair_id")
        if pair_id is None:
            raise FrameworkError("paired-balanced run is missing pair_id")
        by_pair[pair_id][row["variant"]] = row

    pair_rows: list[dict[str, Any]] = []
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for pair_id in sorted(by_pair):
        pair = by_pair[pair_id]
        if set(pair) != {baseline, candidate}:
            raise FrameworkError(
                f"pair {pair_id} does not contain exactly {baseline} and {candidate}"
            )
        base_row = pair[baseline]
        cand_row = pair[candidate]
        base_params = {name: base_row[name] for name in parameter_names}
        cand_params = {name: cand_row[name] for name in parameter_names}
        if base_params != cand_params:
            raise FrameworkError(f"pair {pair_id} parameter mismatch")
        if base_row.get("repetition") != cand_row.get("repetition"):
            raise FrameworkError(f"pair {pair_id} repetition mismatch")

        key = _condition_key(base_params)
        if key not in condition_catalog:
            raise FrameworkError(f"pair {pair_id} has unknown condition")

        baseline_value = float(base_row[PRIMARY_METRIC])
        candidate_value = float(cand_row[PRIMARY_METRIC])
        if baseline_value <= 0:
            raise FrameworkError(f"pair {pair_id} baseline metric must be > 0")
        ratio = candidate_value / baseline_value
        delta = (ratio - 1.0) * 100.0
        winner = "tie"
        if delta > 0:
            winner = "candidate"
        elif delta < 0:
            winner = "baseline"

        result = {
            "condition_id": condition_catalog[key]["condition_id"],
            **base_params,
            "pair_id": pair_id,
            "repetition": base_row.get("repetition"),
            "baseline_variant": baseline,
            "candidate_variant": candidate,
            "baseline_requests_per_second": baseline_value,
            "candidate_requests_per_second": candidate_value,
            "ratio": ratio,
            "delta_percent": delta,
            "winner": winner,
        }
        pair_rows.append(result)
        by_condition[key].append(result)

    paired_json: dict[str, Any] = {}
    for key, group in by_condition.items():
        condition_id = condition_catalog[key]["condition_id"]
        paired_json[condition_id] = {
            "parameters": condition_catalog[key]["parameters"],
            "baseline_variant": baseline,
            "candidate_variant": candidate,
            **_paired_statistics(group),
        }
    return pair_rows, paired_json


def _svg_document(width: int, height: int, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">\n'
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>\n'
        f'{body}'
        '</svg>\n'
    )


def _svg_text(x: float, y: float, text: str, *, size: int = 12, anchor: str = "start") -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="sans-serif" '
        f'font-size="{size}" text-anchor="{anchor}" fill="black">'
        f'{escape(text)}</text>\n'
    )


def _requests_svg(
    variant_summary: dict[str, Any],
    condition_order: list[str],
    condition_catalog: dict[str, dict[str, Any]],
    variants: list[str],
) -> str:
    width, height = 1000, 520
    left, right, top, bottom = 90.0, 40.0, 60.0, 90.0
    plot_w = width - left - right
    plot_h = height - top - bottom

    points: list[tuple[str, str, float]] = []
    for key in condition_order:
        cid = condition_catalog[key]["condition_id"]
        condition = variant_summary.get(cid, {})
        for variant in variants:
            stats = condition.get("variants", {}).get(variant)
            if stats:
                points.append((cid, variant, float(stats["median"])))

    if not points:
        return _svg_document(width, height, _svg_text(width / 2, height / 2, "No analyzed measurements", anchor="middle"))

    y_max = max(value for _, _, value in points) * 1.10
    if y_max <= 0:
        y_max = 1.0

    body = _svg_text(left, 30, "Median HTTP/3 throughput by condition", size=18)
    body += f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="black"/>\n'
    body += f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="black"/>\n'

    for tick in range(6):
        value = y_max * tick / 5
        y = top + plot_h - plot_h * tick / 5
        body += f'<line x1="{left - 4}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="black" stroke-opacity="0.12"/>\n'
        body += _svg_text(left - 8, y + 4, f"{value:.0f}", anchor="end")

    conditions = [condition_catalog[key]["condition_id"] for key in condition_order]
    step = plot_w / max(1, len(conditions))
    offsets = {
        variant: (index - (len(variants) - 1) / 2) * min(24.0, step / max(3, len(variants) + 1))
        for index, variant in enumerate(variants)
    }

    for index, cid in enumerate(conditions):
        x0 = left + step * (index + 0.5)
        body += _svg_text(x0, top + plot_h + 25, cid, anchor="middle")
        condition = variant_summary.get(cid, {})
        for variant in variants:
            stats = condition.get("variants", {}).get(variant)
            if not stats:
                continue
            value = float(stats["median"])
            x = x0 + offsets[variant]
            y = top + plot_h - (value / y_max) * plot_h
            body += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="black"/>\n'
            body += _svg_text(x, y - 10, f"{value:.1f}", size=10, anchor="middle")

    legend_y = height - 25
    legend_x = left
    for index, variant in enumerate(variants):
        x = legend_x + index * 220
        body += f'<circle cx="{x:.2f}" cy="{legend_y - 4}" r="4" fill="black"/>\n'
        body += _svg_text(x + 10, legend_y, variant, size=11)

    body += _svg_text(20, top + plot_h / 2, "requests/s", size=12)
    return _svg_document(width, height, body)


def _paired_svg(pair_rows: list[dict[str, Any]]) -> str:
    width, height = 1000, 520
    if not pair_rows:
        body = _svg_text(60, 35, "Paired throughput delta", size=18)
        body += _svg_text(width / 2, height / 2, "Paired comparison not applicable", anchor="middle")
        return _svg_document(width, height, body)

    left, right, top, bottom = 90.0, 40.0, 60.0, 100.0
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [float(row["delta_percent"]) for row in pair_rows]
    bound = max(1.0, max(abs(value) for value in values) * 1.15)

    body = _svg_text(left, 30, "Paired candidate vs baseline throughput delta", size=18)
    zero_y = top + plot_h / 2
    body += f'<line x1="{left}" y1="{zero_y:.2f}" x2="{left + plot_w}" y2="{zero_y:.2f}" stroke="black"/>\n'

    for tick in (-1.0, -0.5, 0.0, 0.5, 1.0):
        value = bound * tick
        y = zero_y - (value / bound) * (plot_h / 2)
        body += f'<line x1="{left - 4}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="black" stroke-opacity="0.12"/>\n'
        body += _svg_text(left - 8, y + 4, f"{value:+.1f}%", anchor="end")

    step = plot_w / max(1, len(pair_rows))
    for index, row in enumerate(pair_rows):
        value = float(row["delta_percent"])
        x = left + step * (index + 0.5)
        y = zero_y - (value / bound) * (plot_h / 2)
        body += f'<line x1="{x:.2f}" y1="{zero_y:.2f}" x2="{x:.2f}" y2="{y:.2f}" stroke="black" stroke-width="3"/>\n'
        body += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="black"/>\n'
        body += _svg_text(x, top + plot_h + 25, str(row["pair_id"]), size=10, anchor="middle")
        body += _svg_text(x, y - 9 if value >= 0 else y + 18, f"{value:+.2f}%", size=10, anchor="middle")

    body += _svg_text(20, top + plot_h / 2, "delta %", size=12)
    return _svg_document(width, height, body)


def _results_readme(
    experiment_id: str,
    variants: list[str],
    variant_summary: dict[str, Any],
    paired_summary: dict[str, Any],
) -> str:
    lines = [
        f"# Analysis — {experiment_id}",
        "",
        "This directory is generated deterministically from the experiment's raw `measurement.json` files.",
        "Attempt selection is fixed before metric inspection: the first attempt with `execution.valid=true` is selected for every scheduled run.",
        "",
        f"Primary metric: `{PRIMARY_METRIC}`.",
        "Sample standard deviation and coefficient of variation are reported only when `n >= 2`.",
        "",
        "## Variant summaries",
        "",
    ]

    for condition_id in sorted(variant_summary):
        condition = variant_summary[condition_id]
        lines.append(f"### {condition_id}")
        params = json.dumps(condition["parameters"], sort_keys=True, ensure_ascii=False)
        lines.append("")
        lines.append(f"Parameters: `{params}`")
        lines.append("")
        for variant in variants:
            stats = condition["variants"].get(variant)
            if not stats:
                continue
            lines.append(
                f"- `{variant}`: n={stats['n']}, median={stats['median']:.6f}, mean={stats['mean']:.6f} requests/s"
            )
        lines.append("")

    if paired_summary:
        lines.extend(["## Paired comparison", ""])
        for condition_id in sorted(paired_summary):
            stats = paired_summary[condition_id]
            lines.append(
                f"- `{condition_id}`: {stats['candidate_variant']} vs {stats['baseline_variant']}, "
                f"n={stats['n_pairs']}, median delta={stats['median_delta_percent']:+.6f}%, "
                f"wins/losses/ties={stats['wins']}/{stats['losses']}/{stats['ties']}"
            )
        lines.append("")

    lines.extend([
        "## Artifacts",
        "",
        "- `selection.json` — deterministic attempt selection record.",
        "- `runs.csv` — one normalized row per scheduled run.",
        "- `summary.csv` — per-condition, per-variant statistics.",
        "- `pairs.csv` — paired A/B rows when applicable.",
        "- `statistics.json` — structured statistics and analysis policy.",
        "- `analysis-provenance.json` — analysis implementation Git identity.",
        "- `artifacts.sha256` — SHA-256 inventory of generated analysis outputs.",
        "- `../figures/requests-per-second.svg` — median throughput plot.",
        "- `../figures/paired-delta.svg` — paired delta plot.",
        "",
    ])
    return "\n".join(lines)


def _analysis_provenance(experiment_dir: Path) -> dict[str, Any]:
    repo_root = experiment_dir.parents[1]
    source = git_source_info("ngi541-nginx", repo_root, repo_root)
    return {
        "schema_version": 1,
        "implementation": "benchmark/framework/analysis.py",
        "repository": source["name"],
        "commit": source["commit"],
        "describe": source.get("describe"),
        "tracked_dirty": bool(source.get("tracked_dirty")),
        "tracked_diff_sha256": source.get("tracked_diff_sha256"),
        "selection_policy": "first-valid-attempt-by-attempt-number",
        "primary_metric": PRIMARY_METRIC,
    }


def _write_artifact_hashes(experiment_dir: Path, relative_paths: list[str]) -> None:
    lines = []
    for rel in sorted(relative_paths):
        digest = sha256_file(experiment_dir / rel)
        lines.append(f"{digest}  {rel}")
    atomic_write_text(
        experiment_dir / "processed" / "artifacts.sha256",
        "\n".join(lines) + "\n",
    )


def analyze_experiment(experiment_dir: Path) -> dict[str, Any]:
    schedule = read_json(experiment_dir / "execution" / "schedule.json")
    resolved = read_json(experiment_dir / "config" / "resolved.json")
    variants = list(resolved["variants"])

    rows, selections = _normalize_runs(experiment_dir, schedule)
    condition_order, condition_catalog = _condition_catalog(schedule)
    parameter_names = _parameter_names(schedule)

    summary_rows, variant_summary = _build_variant_summary(
        rows,
        condition_order,
        condition_catalog,
        variants,
        parameter_names,
    )
    pair_rows, paired_summary = _build_pairs(
        rows,
        schedule,
        condition_catalog,
        variants,
        parameter_names,
    )

    selection_doc = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "experiment_id": experiment_dir.name,
        "policy": {
            "validity_predicate": "execution.valid == true",
            "selection": "lowest attempt number satisfying validity predicate",
            "metric_independent": True,
            "later_valid_attempts": "ignored",
        },
        "runs": selections,
    }
    atomic_write_json(experiment_dir / "processed" / "selection.json", selection_doc)

    run_fields = [
        "experiment_id", "sequence", "run_id", "pair_id", "variant",
        "repetition", "attempt", *parameter_names,
        "planned_requests", "completed_requests", "elapsed_ns",
        PRIMARY_METRIC,
    ]
    atomic_write_text(
        experiment_dir / "processed" / "runs.csv",
        _csv_text(run_fields, rows),
    )

    summary_fields = [
        "condition_id", *parameter_names, "variant", "n", "mean", "median",
        "min", "max", "sample_standard_deviation",
        "coefficient_of_variation_percent",
    ]
    atomic_write_text(
        experiment_dir / "processed" / "summary.csv",
        _csv_text(summary_fields, summary_rows),
    )

    pair_fields = [
        "condition_id", *parameter_names, "pair_id", "repetition",
        "baseline_variant", "candidate_variant",
        "baseline_requests_per_second", "candidate_requests_per_second",
        "ratio", "delta_percent", "winner",
    ]
    atomic_write_text(
        experiment_dir / "processed" / "pairs.csv",
        _csv_text(pair_fields, pair_rows),
    )

    statistics_doc = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "experiment_id": experiment_dir.name,
        "primary_metric": PRIMARY_METRIC,
        "analysis_policy": {
            "attempt_selection": "first-valid-attempt-by-attempt-number",
            "standard_deviation": "sample (n-1); null when n < 2",
            "coefficient_of_variation": "sample_standard_deviation / mean * 100; null when unavailable",
            "paired_baseline_variant": variants[0] if variants else None,
            "paired_candidate_variant": variants[1] if len(variants) == 2 else None,
            "paired_delta": "(candidate / baseline - 1) * 100",
            "geometric_mean_ratio": "exp(mean(log(candidate / baseline))); positive ratios only",
        },
        "conditions": variant_summary,
        "paired": paired_summary,
    }
    atomic_write_json(
        experiment_dir / "processed" / "statistics.json",
        statistics_doc,
    )

    provenance_doc = _analysis_provenance(experiment_dir)
    atomic_write_json(
        experiment_dir / "processed" / "analysis-provenance.json",
        provenance_doc,
    )

    atomic_write_text(
        experiment_dir / "figures" / "requests-per-second.svg",
        _requests_svg(
            variant_summary,
            condition_order,
            condition_catalog,
            variants,
        ),
    )
    atomic_write_text(
        experiment_dir / "figures" / "paired-delta.svg",
        _paired_svg(pair_rows),
    )
    atomic_write_text(
        experiment_dir / "processed" / "README.md",
        _results_readme(
            experiment_dir.name,
            variants,
            variant_summary,
            paired_summary,
        ),
    )

    generated = [
        "processed/selection.json",
        "processed/runs.csv",
        "processed/summary.csv",
        "processed/pairs.csv",
        "processed/statistics.json",
        "processed/analysis-provenance.json",
        "processed/README.md",
        "figures/requests-per-second.svg",
        "figures/paired-delta.svg",
    ]
    _write_artifact_hashes(experiment_dir, generated)

    return {
        "selected_runs": len(rows),
        "conditions": len(condition_order),
        "pairs": len(pair_rows),
        "variants": variants,
        "analysis_provenance": provenance_doc,
    }


def validate_analysis_outputs(experiment_dir: Path) -> list[str]:
    errors: list[str] = []
    required = [
        "processed/selection.json",
        "processed/runs.csv",
        "processed/summary.csv",
        "processed/pairs.csv",
        "processed/statistics.json",
        "processed/analysis-provenance.json",
        "processed/README.md",
        "processed/artifacts.sha256",
        "figures/requests-per-second.svg",
        "figures/paired-delta.svg",
    ]
    for rel in required:
        if not (experiment_dir / rel).is_file():
            errors.append(f"analysis output missing file: {rel}")

    stats_path = experiment_dir / "processed" / "statistics.json"
    if stats_path.is_file():
        try:
            stats = read_json(stats_path)
            if stats.get("experiment_id") != experiment_dir.name:
                errors.append("statistics.json experiment_id does not match directory")
            if stats.get("primary_metric") != PRIMARY_METRIC:
                errors.append("statistics.json primary_metric is unexpected")
        except FrameworkError as exc:
            errors.append(str(exc))

    hashes_path = experiment_dir / "processed" / "artifacts.sha256"
    if hashes_path.is_file():
        for line in hashes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                expected, rel = line.split("  ", 1)
            except ValueError:
                errors.append("invalid processed/artifacts.sha256 line")
                continue
            path = experiment_dir / rel
            if not path.is_file():
                errors.append(f"hashed analysis artifact missing: {rel}")
                continue
            actual = sha256_file(path)
            if actual != expected:
                errors.append(f"analysis artifact hash mismatch: {rel}")

    return errors
