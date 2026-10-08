# Benchmark framework

The `benchmark/` directory contains reusable benchmark machinery for evaluating NGI541 in network data paths.

It is intentionally independent from any specific execution environment or individual experiment campaign.

## Responsibilities

The benchmark layer may contain:

- workload definitions;
- protocol- and application-specific benchmark configurations;
- reusable benchmark runners;
- primitive-level microbenchmarks;
- measurement helpers;
- deterministic analysis code.

The expected structure is:

```text
benchmark/
├── workloads/
│   ├── primitives/
│   ├── http3/
│   ├── tls13/
│   └── reverse-proxy/
├── configs/
├── runner/
└── analysis/
```

Directories should be introduced together with real implementation. Empty placeholders are not required.

## Boundary

`benchmark/` does not provision machines, describe a particular historical campaign, or contain project-level performance claims.

Those responsibilities belong to:

```text
environments/  execution environment and provisioning
experiments/   concrete reproducible campaigns and their results
evidence/      accepted project evidence and scoped claims
```

## Design requirements

Benchmark execution must make workload parameters explicit.

Parameters such as payload size, connection concurrency, worker count, protocol mode, warm-up policy, measurement duration or request count, cipher suite, traffic direction, connection lifetime, and integration mode must not depend on undocumented host state.

Raw measurements must be preserved before statistical processing.

Analysis must be deterministic from the preserved experiment inputs and raw results.

The framework must support both protocol-level workloads and isolated cryptographic execution measurements.

## Planned workload classes

The benchmark framework is expected to grow around several complementary workload classes:

- primitive execution;
- NGINX HTTP/3 over QUIC;
- TLS 1.3 over TCP;
- TLS reverse proxy;
- long-lived TLS connections;
- small-message and high-concurrency workloads;
- additional network data-plane workloads when they provide a concrete research or adoption target.

See:

- [`../docs/benchmark-methodology.md`](../docs/benchmark-methodology.md)
- [`../docs/experimental-scope.md`](../docs/experimental-scope.md)
- [`../docs/integration-model.md`](../docs/integration-model.md)
