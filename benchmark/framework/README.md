# Experiment framework core

This directory implements the portable R5 experiment framework.

The core is intentionally Python 3 standard-library only.

## R5.2 scope

R5.2 implements:

- experiment ID generation;
- common experiment directory generation;
- immutable request capture;
- atomic lifecycle-state persistence;
- transition rules;
- common request resolution;
- deterministic parameter-matrix expansion;
- balanced A/B schedule generation;
- randomized schedule generation with a recorded seed;
- append-only attempt-directory allocation;
- structural experiment validation;
- a stable shell entry point;
- standard-library unit tests.

R5.2 does **not** yet execute NGINX, collect DUT inventory, build NGI541, produce performance measurements, analyze results, or promote evidence.

Those functions are intentionally layered on top of this core.

## Entry point

Use:

```bash
./scripts/experiment.sh
```

The shell wrapper only locates the repository and invokes the Python core.

## Create an experiment

Example:

```bash
./scripts/experiment.sh create \
  --workload http3 \
  --environment local \
  --variant stock \
  --variant ngi541-direct \
  --repetitions 5 \
  --param 'payload_bytes=[1024,16384]' \
  --param 'workers=[1,2,4]' \
  --param 'clients=[1,8,16]'
```

The command prints the generated experiment ID and path.

Creation produces the common filesystem ABI, preserves `config/request.json`, creates `state.json`, and enters `PREPARING`.

## Generate the execution plan

```bash
./scripts/experiment.sh plan <experiment-id>
```

The plan command:

1. validates `request.json`;
2. resolves common defaults;
3. writes immutable `config/resolved.json`;
4. expands list-valued parameters as matrix axes;
5. generates immutable `execution/schedule.json`;
6. records the planned run count in `state.json`.

The experiment remains in `PREPARING`.

A later preparation layer must collect environment/provenance data and pass correctness gates before the experiment can transition to `READY`.

## Parameter convention

For the R5 core:

- scalar parameter values are fixed across the experiment;
- list parameter values are matrix axes;
- `repetitions` is a positive integer and is not a matrix axis.

Matrix axis names are sorted before Cartesian expansion so the generated schedule is deterministic from the resolved request.

## Comparison modes

Supported modes:

```text
single
fixed
paired-balanced
randomized
```

Default selection:

- one variant → `single`;
- two variants → `paired-balanced`;
- more than two variants → `fixed`.

`paired-balanced` requires exactly two variants and alternates order by comparison group:

```text
pair 1: A → B
pair 2: B → A
pair 3: A → B
```

`randomized` uses a recorded integer seed. If no seed is provided, R5.2 resolves the seed to `0` to preserve deterministic behavior.

## Inspect state

```bash
./scripts/experiment.sh status <experiment-id>
```

or:

```bash
./scripts/experiment.sh status <experiment-id> --json
```

## Validate structure

```bash
./scripts/experiment.sh validate <experiment-id>
```

The built-in validator is standard-library only. It checks core invariants without requiring a third-party JSON Schema implementation.

The formal schemas remain under:

```text
benchmark/framework/schemas/
```

## Allocate a raw attempt

Future workload runners use:

```bash
./scripts/experiment.sh allocate-attempt \
  <experiment-id> \
  run-0001
```

The first allocation creates:

```text
raw/runs/run-0001/attempt-01/
```

A second allocation creates:

```text
raw/runs/run-0001/attempt-02/
```

Existing attempts are never overwritten.

## Lifecycle boundary

R5.2 deliberately stops after common planning.

The next implementation layer must provide:

```text
environment adapter
DUT inventory
source/dependency provenance
build/runtime identity
correctness preflight
manifest sealing
READY transition
```

Only after that boundary may measured workload execution begin.

## Tests

Run:

```bash
python3 -m unittest discover \
  -s benchmark/framework/tests \
  -v
```

The tests use only the Python standard library.
