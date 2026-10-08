# Project evidence

The `evidence/` directory contains results that have been accepted as evidence for a specific NGI541 project claim.

It is not a replacement for `experiments/`.

Experiments preserve execution provenance and measurements.

Evidence records the interpretation that the project is prepared to defend from those measurements.

The main evidence classes are:

```text
evidence/
├── functional/
└── performance/
```

## Evidence requirements

Every accepted claim must identify the experiment or validation artifact that supports it.

A performance claim must define its scope and must also state important limitations or conclusions that are not supported by the underlying experiment.

Evidence must not generalize beyond the measured workload, hardware, integration mode, protocol, or metric.

For example, throughput measurements do not establish latency improvement, CPU-efficiency improvement, or universal performance superiority unless those properties were independently measured.

## Relationship to experiments

`evidence/` should avoid duplicating large raw datasets.

Where possible, an evidence record references the canonical experiment and contains only:

- the accepted claim;
- supporting summary data;
- scope;
- limitations;
- links to relevant processed results;
- supersession status when applicable.

Evidence may be marked as:

```text
accepted
superseded
withdrawn
```

A newer experiment may supersede an older claim without deleting the historical experiment that originally supported it.

## Functional evidence

Functional evidence may include:

- regression-test results;
- conformance or validation evidence;
- external validation results;
- negative-path validation;
- compatibility checks.

## Performance evidence

Performance evidence must be derived from a documented experiment and must follow the benchmark methodology.

Project-facing claims should remain narrower than the underlying data whenever the data does not support a broader conclusion.

See:

- [`../docs/reproducibility.md`](../docs/reproducibility.md)
- [`../docs/benchmark-methodology.md`](../docs/benchmark-methodology.md)
