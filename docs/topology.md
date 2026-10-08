# Experimental topologies

NGI541 uses different execution topologies for different stages of development and evaluation.

The topology is part of experiment provenance and must be recorded explicitly.

## T0 — local single-host

```text
┌──────────────────────────────────────────────┐
│ Host                                         │
│                                              │
│ load generator  ⇄  loopback  ⇄  NGINX SUT  │
└──────────────────────────────────────────────┘
```

This topology is intended for:

```text
integration development
functional validation
early performance characterization
benchmark-framework development
```

The historical C2.1 HTTP/3 experiment uses this topology.

Its main limitations are:

- shared CPU scheduling;
- loopback networking;
- contention between the load generator and the system under test;
- limited ability to separate client and server resource consumption.

T0 results must therefore be identified as local or preliminary evidence.

## T1 — dedicated client/server

```text
┌─────────────────┐       network       ┌─────────────────┐
│ Client          │  =================  │ Server / SUT    │
│                 │                     │                 │
│ load generator  │                     │ NGINX + crypto  │
└─────────────────┘                     └─────────────────┘
```

T1 is the primary topology for canonical HTTP/3 and TLS 1.3 server characterization.

The client generates traffic while the server is dedicated to the system under test.

Where possible, the following should be controlled and recorded:

```text
CPU placement
NUMA configuration
network interfaces
CPU frequency policy
IRQ placement
PMU access
```

This is the minimum preferred topology for CloudLab performance evaluation.

## T2 — dedicated client/proxy/origin

```text
┌─────────────┐        ┌─────────────────┐        ┌─────────────┐
│ Client      │        │ Proxy / SUT     │        │ Origin      │
│             │  ====  │                 │  ====  │             │
│ loadgen     │        │ NGINX + NGI541  │        │ upstream    │
└─────────────┘        └─────────────────┘        └─────────────┘
```

T2 is the preferred topology for TLS reverse-proxy evaluation.

It separates client traffic generation, proxy cryptographic execution, and origin-server processing.

This prevents the upstream workload from sharing the proxy's CPU resources and allows both TLS legs to be characterized independently.

A reverse proxy is particularly useful for evaluating persistent prepared-key execution because the system under test can perform both decrypt and encrypt operations across independent downstream and upstream connections.

## Primitive execution topology

Primitive cryptographic benchmarks do not require a network topology.

They run on an isolated target host with explicit CPU and frequency controls where available.

Their purpose is to measure execution characteristics independently from the protocol stack.

## Topology provenance

An experiment should record at least:

```text
node roles
CPU model and topology
memory/NUMA topology
operating system
network interfaces
link properties
CPU affinity
frequency policy
relevant ISA capabilities
```

When CloudLab is used, the experiment should also record the relevant CloudLab profile identity and allocation information required to understand the execution environment.

See also:

- [`reproducibility.md`](reproducibility.md)
- [`benchmark-methodology.md`](benchmark-methodology.md)
