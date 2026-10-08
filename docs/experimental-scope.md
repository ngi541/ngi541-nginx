# Experimental scope

NGI541 is evaluated as a cryptographic execution backend for network data paths.

The project does not define success as implementing the largest possible catalogue of cryptographic algorithms.

The primary research question is:

> How does a standalone prepared-key cryptographic execution backend behave when embedded into real high-throughput network data paths, and under which workloads, integration models, and hardware architectures is that execution model beneficial?

## Evaluation dimensions

The experimental program is organized around four primary dimensions:

```text
cryptographic primitive
integration model
network workload
hardware architecture
```

A complete evaluation therefore requires a matrix rather than a single benchmark.

## Current cryptographic baseline

The current NGI541 baseline includes selected AES and SHA-2 functionality, including AES-GCM and AES-CTR used by the current NGINX QUIC integration.

AES-GCM provides QUIC packet protection for AES-based TLS 1.3 cipher suites.

The current NGINX HTTP/3 integration also uses NGI541 AES execution for QUIC header protection.

## ChaCha20-Poly1305

ChaCha20-Poly1305 is a high-priority future extension.

Without ChaCha20-Poly1305 and the corresponding ChaCha20 QUIC header-protection path, NGI541 does not cover the other major modern QUIC/TLS symmetric cipher family.

Adding this path would also provide an important cross-architecture comparison because ChaCha20-Poly1305 has a substantially different execution structure from AES-GCM and a different dependence on processor cryptographic extensions.

A future evaluation should therefore compare AES-GCM and ChaCha20-Poly1305 across Intel, AMD, and ARM64 systems where suitable hardware is available.

## SHA, HMAC, and HKDF

Additional SHA variants are not automatically required for the current data-path execution model.

In TLS 1.3, the SHA component of a cipher-suite name participates in transcript hashing and key derivation rather than record encryption itself.

As long as the surrounding TLS implementation owns handshake and key derivation, NGI541 can accelerate selected symmetric execution without taking ownership of those operations.

If the project later expands into TLS key-schedule execution, the relevant scope should include:

```text
SHA-384
HMAC-SHA-256
HMAC-SHA-384
HKDF-SHA-256
HKDF-SHA-384
```

SHA-512 and additional general-purpose hash algorithms are lower priority unless a concrete network consumer requires them.

## Workload scope

The planned evaluation includes several complementary workload classes.

### Primitive execution

Isolates cryptographic execution from protocol and networking effects.

### NGINX HTTP/3

Exercises QUIC packet protection and header protection in a real server data path.

This is the first implemented reference integration.

### TLS 1.3 over TCP

Evaluates symmetric TLS record protection in conventional HTTPS and HTTP/2 traffic.

Because TLS record protection is owned by the TLS implementation, this workload requires a different integration boundary from the direct NGINX QUIC path.

### TLS reverse proxy

Evaluates simultaneous cryptographic work across downstream and upstream connections.

This workload is important because a proxy may decrypt on one connection, encrypt on another, and process traffic in both directions using multiple persistent key contexts.

### Additional network workloads

Future workloads may include:

- long-lived TLS connections;
- small-message HTTP/2 or RPC traffic;
- bidirectional QUIC traffic;
- other high-throughput network data paths where symmetric cryptographic execution is a material part of runtime cost.

IPsec or other packet-processing integrations may be evaluated separately when they provide a concrete adoption or research target.

## Hardware scope

The target architecture set is:

```text
Intel x86_64
AMD x86_64
ARM64
```

Experiments should record relevant processor capabilities rather than treating all systems of one architecture as equivalent.

For x86 systems this may include:

```text
AES-NI
PCLMULQDQ
AVX2
VAES
VPCLMULQDQ
```

where applicable.

## Current non-goals

NGI541 does not currently attempt to replace a complete TLS or PKI stack.

The surrounding protocol implementation may continue to own:

```text
certificate processing
certificate validation
TLS handshake state
key exchange
PKI
protocol state machines
```

The current project also makes no general side-channel-resistance claim beyond properties that have been explicitly reviewed and validated.

Side-channel evaluation requires a dedicated methodology and evidence set.

## Interpretation

The purpose of the experimental program is not to prove that NGI541 is universally faster than another cryptographic library.

The objective is to determine:

- where prepared-key and direct-execution architecture provides measurable value;
- where abstraction overhead matters;
- how results change across protocol workloads and hardware architectures;
- where system-level bottlenecks dominate the cryptographic execution path.

See also:

- [`integration-model.md`](integration-model.md)
- [`benchmark-methodology.md`](benchmark-methodology.md)
- [`topology.md`](topology.md)
