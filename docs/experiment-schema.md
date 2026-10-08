# Experiment schema

This document defines the filesystem and data contract for generated NGI541 benchmark experiments.

The contract is shared by local, manually allocated bare-metal, and CloudLab execution. Workloads may add workload-specific parameters and observations, but they must not redefine the top-level experiment layout.

Historical experiments that predate this contract, such as `c2.1-local-http3`, remain preserved in their historical form.

## Design goals

The experiment format is designed around the following requirements:

- one common layout for every workload and execution environment;
- automatic generation of experiment directories and metadata;
- no host-specific absolute paths in generated experiment metadata;
- immutable source, configuration, schedule, and raw measurement records;
- append-only retry history;
- portable machine-readable data;
- deterministic regeneration of processed results and figures;
- support for single-node and multi-node topologies;
- no mandatory Python dependencies outside the standard library;
- enough provenance to understand an experiment without access to the original DUT.

An experiment directory must be self-describing without access to the machine on which it was produced.

## Canonical machine format

Generated framework metadata uses JSON.

JSON is the canonical format because Python 3 can parse and generate it using the standard library. The core experiment framework must not require PyYAML, NumPy, pandas, matplotlib, or similar packages.

Human-facing README files and CSV summaries may be generated from canonical JSON records.

## Experiment identifier

Experiment identifiers are generated automatically.

Format:

```text
<workload>-<environment>-<UTC timestamp>-<short-id>
```

Examples:

```text
http3-local-20261009T214512Z-a31f92
http3-cloudlab-20261010T083122Z-e27bc1
tls13-baremetal-20261011T142004Z-c3f810
reverse-proxy-cloudlab-20261012T101311Z-94ab72
```

The identifier must match:

```text
^[a-z0-9][a-z0-9-]*-[a-z0-9][a-z0-9-]*-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{6}$
```

The generated identifier is immutable. A curated alias may be added later for publication-facing use, but it does not replace the generated identifier.

## Common experiment filesystem ABI

Every generated experiment uses the same top-level structure:

```text
experiments/
└── <experiment-id>/
    ├── README.md
    ├── manifest.json
    ├── state.json
    ├── config/
    │   ├── request.json
    │   └── resolved.json
    ├── environment/
    │   ├── adapter.json
    │   └── nodes/
    │       └── <node-name>/
    │           ├── system.json
    │           ├── cpu.json
    │           ├── memory.json
    │           └── network.json
    ├── provenance/
    │   ├── sources.json
    │   ├── dependencies.json
    │   ├── build.json
    │   └── binaries.sha256
    ├── execution/
    │   └── schedule.json
    ├── raw/
    │   └── runs/
    │       └── run-0001/
    │           └── attempt-01/
    │               ├── measurement.json
    │               ├── stdout.log
    │               └── stderr.log
    ├── processed/
    │   ├── summary.csv
    │   └── statistics.json
    ├── figures/
    └── logs/
        └── framework.log
```

Workload implementations may add files below existing semantic directories when required, but they must not replace or rename the common top-level contract.

## Request versus resolved configuration

`config/request.json` records exactly what the user requested.

`config/resolved.json` records the validated configuration after framework defaults, environment resolution, and workload-specific expansion have been applied.

The request is immutable after creation.

The resolved configuration is immutable once the experiment reaches `READY`.

## `manifest.json`

The manifest is the immutable identity record for the experiment.

It is created after environment preparation and provenance discovery, but before the first measured run.

The manifest references:

- experiment identity;
- framework revision;
- software identities;
- topology;
- configuration;
- normalized environment records;
- provenance records;
- execution schedule.

It must not be used as a mutable status file.

Machine-readable schema:

[`../benchmark/framework/schemas/manifest.schema.json`](../benchmark/framework/schemas/manifest.schema.json)

## `state.json`

`state.json` is the mutable lifecycle record.

It contains the current lifecycle state, timestamps, progress counters, and failure information.

It is the only core experiment metadata file expected to be updated repeatedly during execution.

Machine-readable schema:

[`../benchmark/framework/schemas/state.schema.json`](../benchmark/framework/schemas/state.schema.json)

## `execution/schedule.json`

The execution schedule is generated before measured execution begins.

It defines the complete ordering of planned runs, including:

- sequence number;
- run identifier;
- comparison pair identifier when applicable;
- variant;
- repetition number;
- workload parameters.

Balanced A/B ordering must be resolved before execution. The runner must not invent comparison order dynamically.

Machine-readable schema:

[`../benchmark/framework/schemas/schedule.schema.json`](../benchmark/framework/schemas/schedule.schema.json)

## Raw runs and attempts

Every planned run has a stable `run-XXXX` identifier.

Retries never overwrite earlier attempts.

Example:

```text
raw/runs/run-0007/
├── attempt-01/
│   ├── measurement.json
│   ├── stdout.log
│   └── stderr.log
└── attempt-02/
    ├── measurement.json
    ├── stdout.log
    └── stderr.log
```

A failed attempt remains part of the raw record.

The analysis stage determines which attempt is valid for statistical processing according to explicit rules.

## `measurement.json`

Every execution attempt produces a `measurement.json`.

The measurement record contains:

- experiment identifier;
- run identifier;
- attempt number;
- variant;
- resolved run parameters;
- timing information;
- request or operation counters;
- primary and secondary metrics;
- process exit status;
- validity state;
- optional failure reason;
- workload-specific observations.

Machine-readable schema:

[`../benchmark/framework/schemas/measurement.schema.json`](../benchmark/framework/schemas/measurement.schema.json)

## Node model

Environment metadata is node-oriented from the beginning.

A local T0 experiment may use one node with both roles:

```json
{
  "nodes": {
    "host": {
      "roles": ["load-generator", "dut"]
    }
  }
}
```

A dedicated client/server experiment may use:

```json
{
  "nodes": {
    "client": {
      "roles": ["load-generator"]
    },
    "server": {
      "roles": ["dut"]
    }
  }
}
```

A reverse-proxy experiment may use:

```json
{
  "nodes": {
    "client": {
      "roles": ["load-generator"]
    },
    "proxy": {
      "roles": ["dut"]
    },
    "origin": {
      "roles": ["upstream"]
    }
  }
}
```

Local, bare-metal, and CloudLab adapters may discover machines differently, but they must normalize them into the same node model.

## Variant identifiers

Core variant identifiers are stable:

```text
stock
ngi541-direct
ngi541-provider
```

Temporary implementation names such as `patched`, `custom`, or local build-directory names must not be used as canonical variant identifiers.

## Time notation

Human-readable timestamps use UTC RFC 3339:

```text
2026-10-09T21:45:12Z
```

Measured elapsed time uses integer nanoseconds where possible:

```json
{
  "elapsed_ns": 26499123874
}
```

## Immutability policy

| Artifact | Policy |
| --- | --- |
| `config/request.json` | immutable |
| `config/resolved.json` | immutable after `READY` |
| `manifest.json` | immutable after `READY` |
| `execution/schedule.json` | immutable after `READY` |
| `environment/**` | immutable after `READY` |
| `provenance/**` | immutable after `READY` |
| `raw/**` | append-only |
| `state.json` | mutable lifecycle state |
| `processed/**` | regenerable |
| `figures/**` | regenerable |
| generated `README.md` | regenerable |
| `logs/framework.log` | append-only |

## Processed results

Processed results must be derivable from preserved raw attempts plus explicit analysis rules.

At minimum:

```text
processed/summary.csv
processed/statistics.json
```

Outliers remain in raw data. Any excluded attempt or run must remain present and the exclusion reason must be represented in processed analysis metadata.

## Figures

Figures are derived artifacts.

The default framework should generate SVG with Python 3 standard-library code where practical.

Figures must be reproducible from processed data and must not be treated as the primary measurement record.

## Evidence relationship

Experiment execution and evidence acceptance are separate operations.

```text
experiment
    ↓
evidence candidate
    ↓
explicit review / promotion
    ↓
accepted evidence
```

A completed experiment must not automatically become an accepted project claim.

## Self-description requirement

A frozen experiment must provide enough information to answer, without shell history or access to the original host:

```text
what ran
where it ran
which revisions were used
which binaries were executed
which topology was used
which parameters were resolved
which order was executed
which attempts failed
which raw measurements were produced
how the processed result was derived
```
