# C2.1 local HTTP/3 performance evidence

Status: **accepted preliminary local evidence**

This evidence record summarizes the project-facing conclusion supported by the first frozen NGINX HTTP/3 performance experiment.

Canonical experiment:

[`experiments/c2.1-local-http3/`](../../../experiments/c2.1-local-http3/)

## Accepted claim

> In the current NGINX HTTP/3 integration, NGI541 reaches parity with the stock OpenSSL path at low concurrency and shows a repeatable approximately 4–6% median throughput advantage in sustained multi-connection 16 KiB workloads.

The strongest points supporting the 4–6% portion of the claim are:

| Payload | Workers | Clients | Stock median req/s | NGI541 median req/s | Median delta | NGI541 wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 KiB | 2 | 16 | 8786.95 | 9283.03 | +5.65% | 5/5 |
| 16 KiB | 4 | 16 | 9082.30 | 9456.88 | +4.12% | 5/5 |

Low-concurrency parity is represented by the 16 KiB, 1-worker / 1-client point:

```text
Stock OpenSSL: 3242.79 requests/s
NGI541:        3242.95 requests/s
```

The 1 KiB, 2-worker / 16-client workload is also approximately at parity by median (+0.50%).

## Throughput comparison

![HTTP/3 throughput comparison](../../../experiments/c2.1-local-http3/figures/throughput-comparison.svg)

## Relative median delta

![Relative throughput delta](../../../experiments/c2.1-local-http3/figures/relative-throughput-delta.svg)

## Scope and limitations

This is single-host loopback evidence.

The load generator and NGINX system under test shared the same physical host and CPU resources.

At higher concurrency, host scheduling, loopback networking, and contention prevent reliable separation of the cryptographic execution effect from host-level bottlenecks.

The 4-worker / 32-client point is therefore not used to broaden the central claim.

The 2-worker / 8-client accepted set has a positive median result, but contains two pathological NGI541 drops. It is not used as the basis of the 4–6% statement.

## Raw-data disclosure

Per-run machine-readable output containing the accepted benchmark measurements was not preserved.

The project preserved historical runners, configurations, payloads, source/build provenance, and the historical NGI541 runtime identity, but the summary values are a reconstructed canonical summary from the original benchmark session record.

This evidence must therefore remain classified as preliminary local evidence until it is superseded by a dedicated reproducible client/server campaign with preserved per-run raw data.

## Not established by this evidence

This experiment does **not** establish:

- universal performance superiority over OpenSSL;
- a latency improvement;
- lower CPU utilization;
- improved cycles per byte;
- improved energy efficiency;
- performance on AMD systems;
- performance on ARM64 systems;
- performance outside this NGINX HTTP/3 integration;
- causal attribution of the complete end-to-end delta to AES-GCM alone;
- bit-identical reproduction of the historical benchmark executable.

## Next validation level

The next performance-evidence level is dedicated client/server evaluation with controlled CPU placement, hardware counters, preserved raw measurements, and heterogeneous Intel/AMD/ARM64 systems.

See:

- [`docs/benchmark-methodology.md`](../../../docs/benchmark-methodology.md)
- [`docs/topology.md`](../../../docs/topology.md)
- [`docs/experimental-scope.md`](../../../docs/experimental-scope.md)
- [`docs/reproducibility.md`](../../../docs/reproducibility.md)
