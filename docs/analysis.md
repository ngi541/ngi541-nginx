# Deterministic analysis contract

R5.5 converts frozen raw experiment measurements into reproducible machine-readable summaries and dependency-free figures.

## Input boundary

Analysis consumes only experiment-owned data:

```text
config/resolved.json
execution/schedule.json
raw/runs/<run-id>/attempt-*/measurement.json
```

It never reruns NGINX, curl, or the workload.

## Attempt selection

Retries are allowed only by the execution layer after operational invalidity. Analysis prevents retry selection bias with one fixed rule:

```text
select the lowest-numbered attempt whose execution.valid is true
```

Metric values are not inspected when choosing the attempt. Later attempts are recorded as ignored. If the first valid attempt is malformed, analysis fails; it does not select a later attempt.

## Normalization

`processed/runs.csv` contains one selected row per scheduled run and preserves schedule sequence, pair identity, variant, repetition, workload parameters, request counts, elapsed time, and the primary metric.

`processed/selection.json` records the selected attempt number and the number of earlier invalid and later ignored attempts for every run.

## Statistics

For each condition and variant:

```text
n
mean
median
min
max
sample standard deviation (n - 1)
coefficient of variation (%)
```

Dispersion fields are null for a single observation.

For `paired-balanced` experiments with two variants, the resolved variant order defines:

```text
variants[0] = baseline
variants[1] = candidate
```

Per-pair ratio and delta are:

```text
ratio = candidate / baseline
delta_percent = (ratio - 1) * 100
```

Condition-level paired statistics include mean and median delta, min/max delta, sample standard deviation of deltas, wins/losses/ties, and geometric-mean ratio when all ratios are positive.

## Determinism and integrity

Generated CSV, JSON, Markdown, and SVG files contain no current-time field. Re-running the analysis against identical raw inputs and the same analysis implementation produces byte-identical result artifacts.

`processed/analysis-provenance.json` records the Git identity of the analysis implementation. `processed/artifacts.sha256` fingerprints every generated result artifact except itself. COMPLETE-state validation recomputes these hashes.

## Lifecycle

```text
ANALYZING --analyze--> COMPLETE
```

An analysis failure transitions to `FAILED` with stage `analyzing`. Re-running `analyze` resumes only analysis-stage failures; it cannot mask preparation or execution failures.
