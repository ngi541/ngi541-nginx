# Experiment framework core

This directory implements the portable R5 experiment framework.

The core is Python 3 standard-library only.

## Implemented through R5.3

The framework currently provides:

- experiment ID generation;
- common experiment directory generation;
- immutable request capture;
- atomic lifecycle-state persistence;
- common request resolution;
- deterministic parameter-matrix expansion;
- balanced A/B scheduling;
- append-only attempt allocation;
- local environment adapter;
- normalized local system/CPU/memory/network inventory;
- Git source provenance;
- tool/dependency discovery;
- optional binary SHA-256 fingerprinting;
- preparation preflight hooks;
- manifest generation and sealing;
- `PREPARING -> READY` transition;
- generated prepared-experiment README;
- structural validation;
- Python standard-library unit tests.

R5.3 still does **not** execute measured HTTP/3 workloads or analyze benchmark results.

## User-facing flow

Create:

```bash
./scripts/experiment.sh create \
  --workload http3 \
  --environment local \
  --variant stock \
  --variant ngi541-direct \
  --repetitions 5 \
  --param 'payload_bytes=[1024,16384]' \
  --param 'workers=[2]' \
  --param 'clients=[16]'
```

Plan:

```bash
./scripts/experiment.sh plan <experiment-id>
```

Prepare:

```bash
./scripts/experiment.sh prepare <experiment-id>
```

R5.3 automatically records the `ngi541-nginx` Git repository and, when present as a sibling Git work tree, `../ngi541`.

Additional sources may be supplied:

```bash
./scripts/experiment.sh prepare <experiment-id> \
  --source custom-source=/path/to/source
```

Runtime artifacts may be fingerprinted:

```bash
./scripts/experiment.sh prepare <experiment-id> \
  --binary stock-nginx=/path/to/stock/nginx \
  --binary ngi541-nginx=/path/to/ngi541/nginx
```

Additional correctness or preparation checks may be executed:

```bash
./scripts/experiment.sh prepare <experiment-id> \
  --preflight 'core-tests=./path/to/test-command' \
  --preflight 'integration-tests=./scripts/test.sh'
```

Each custom preflight command gets persistent stdout/stderr logs under:

```text
provenance/preflight/
```

A failed preflight transitions the experiment to `FAILED` and preserves all preparation artifacts collected so far.

After correcting the problem, running `prepare` again resumes through:

```text
FAILED -> PREPARING
```

Seal:

```bash
./scripts/experiment.sh seal <experiment-id>
```

Sealing requires passing preflight and all required preparation records.

It creates:

```text
manifest.json
README.md
```

and transitions:

```text
PREPARING -> READY
```

At `READY`, configuration, environment, provenance, schedule, and manifest records become the immutable pre-run experiment identity.

## Local adapter

The R5.3 local adapter produces:

```text
environment/adapter.json
environment/nodes/host/system.json
environment/nodes/host/cpu.json
environment/nodes/host/memory.json
environment/nodes/host/network.json
```

The local topology is:

```text
T0
host:
  load-generator
  dut
```

Linux and macOS use different discovery mechanisms but emit the same normalized file layout.

## Source provenance

`provenance/sources.json` records Git identity including:

- commit;
- branch;
- describe result;
- origin remote when available;
- dirty state;
- tracked-diff SHA-256;
- relevant untracked filenames.

Generated experiment directories and Python bytecode are excluded from the relevant-untracked calculation.

A dirty source is recorded but does not automatically prevent an experimental run at R5.3.

Later evidence-promotion policy may require clean sources for accepted evidence.

## Dependencies

`provenance/dependencies.json` probes common tools when available:

```text
python3
git
curl
cmake
clang
openssl
```

It also records pinned values from:

```text
integration/versions/versions.env
```

when present.

## Binary fingerprints

Every `--binary NAME=PATH` artifact is hashed with SHA-256.

The canonical textual fingerprint file is:

```text
provenance/binaries.sha256
```

Additional binary metadata is recorded in:

```text
provenance/build.json
```

Absolute host paths are not emitted into the experiment metadata.

## Preparation versus sealing

Preparation remains mutable because a failed preparation may be retried.

Sealing is the boundary that makes pre-run experiment identity immutable.

This separation is deliberate:

```text
PREPARING
  collect / retry / correct
      ↓
seal
      ↓
READY
  immutable pre-run identity
```

## Next layer

The next framework layer adds workload execution.

For HTTP/3 this will consume the immutable schedule, launch the selected variant, perform warmup and measured client execution, write `measurement.json` for every attempt, and preserve stdout/stderr without changing the R5 experiment ABI.
