# Experiments

The `experiments/` directory contains concrete NGI541 evaluation campaigns.

An experiment binds together immutable source identities, dependency versions, an execution environment, a benchmark workload, explicit parameters, raw measurements, and analysis outputs.

`benchmark/` defines how measurements can be produced.

`experiments/` records what was actually executed.

## Experiment identity

Each campaign has a stable identifier, for example:

```text
c2.1-local-http3
cloudlab-http3-intel-v1
cloudlab-tls13-amd-v1
cloudlab-reverse-proxy-arm64-v1
```

A frozen experiment must not be silently rewritten.

A methodological or execution change that can alter the interpretation of results requires a new experiment identity or an explicitly versioned campaign.

## Expected contents

A normal experiment may contain:

```text
experiments/<experiment-id>/
├── manifest.yaml
├── README.md
├── provenance/
├── raw/
├── processed/
└── figures/
```

Historical experiments may preserve their original runner, configuration, and payload artifacts under a dedicated `historical/` directory when those files predate the reusable benchmark framework.

## Manifest

The experiment manifest is the central provenance record.

It should identify, as applicable:

- NGI541 source commit;
- integration repository commit;
- dependency versions and checksums;
- compiler and build profile;
- relevant binary fingerprints;
- execution environment;
- hardware and operating system;
- network topology;
- integration mode;
- protocol and cipher suite;
- workload parameters;
- warm-up and repetition policy;
- measurement protocol;
- analysis revision.

## Raw and processed data

Raw measurements are immutable experiment inputs.

Processed tables, summaries, and figures must be reproducible from raw data and the recorded analysis code.

Outliers must remain present in the preserved raw dataset.

If an analysis excludes a measurement, the exclusion rule and reason must be explicit and reproducible.

## Historical fidelity

Historical artifacts must preserve what actually ran.

They must not be rewritten merely to make them resemble the current portable benchmark framework.

This is especially important for absolute paths, old runner conventions, build paths, or other details that are relevant to forensic provenance.

See:

- [`../docs/reproducibility.md`](../docs/reproducibility.md)
- [`../docs/benchmark-methodology.md`](../docs/benchmark-methodology.md)
