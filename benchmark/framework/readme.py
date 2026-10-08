from __future__ import annotations

from pathlib import Path

from framework.io_utils import read_json


def generate_prepared_readme(experiment_dir: Path) -> str:
    manifest = read_json(experiment_dir / "manifest.json")
    schedule = read_json(experiment_dir / "execution" / "schedule.json")
    preflight = read_json(experiment_dir / "provenance" / "preflight.json")

    exp = manifest["experiment"]
    topology = manifest["topology"]
    variants = []

    for run in schedule["runs"]:
        variant = run["variant"]
        if variant not in variants:
            variants.append(variant)

    dirty_sources = [
        name
        for name, dirty in manifest
        .get("extensions", {})
        .get("source_dirty", {})
        .items()
        if dirty
    ]

    dirty_note = "none"
    if dirty_sources:
        dirty_note = ", ".join(dirty_sources)

    return f"""# {exp["id"]}

Generated NGI541 experiment record.

## Preparation status

```text
state: READY
workload: {exp["workload"]}
environment: {exp["environment"]}
topology: {topology["class"]}
planned runs: {len(schedule["runs"])}
comparison mode: {schedule["comparison_mode"]}
variants: {", ".join(variants)}
preflight: {"PASS" if preflight["passed"] else "FAIL"}
dirty recorded sources: {dirty_note}
```

## Canonical records

```text
manifest.json
config/request.json
config/resolved.json
environment/
provenance/
execution/schedule.json
state.json
```

Raw measurements will be appended below:

```text
raw/runs/
```

Processed outputs and figures are derived artifacts and are generated after measured execution.

This README is generated from the experiment metadata and may be regenerated.
"""
