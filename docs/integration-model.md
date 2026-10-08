# Integration model

NGI541 is designed to provide cryptographic execution without taking ownership of the surrounding network protocol stack.

Different protocols expose different integration boundaries.

The project therefore distinguishes between direct data-path integration and cryptographic-provider integration.

## Direct public API integration

In direct integration, the protocol implementation explicitly creates NGI541 prepared-key objects and invokes NGI541 execution functions from its data path.

Conceptually:

```text
protocol stack
     │
     │ keys / packet buffers
     ▼
NGI541 public prepared-key API
     │
     ▼
cryptographic execution
```

This model gives the consumer explicit control over where NGI541 enters the data path.

It also minimizes intermediate abstraction between the protocol implementation and the cryptographic operation.

## Current NGINX HTTP/3 integration

The NGINX QUIC integration uses this direct model.

The surrounding TLS implementation continues to own:

- TLS 1.3 handshake;
- certificate handling;
- key derivation.

NGINX provides the resulting QUIC protection keys to its packet-protection layer.

For supported AES-based paths, NGI541 performs selected packet- and header-protection operations through its public prepared-key API.

Conceptually:

```text
OpenSSL
  │
  │ TLS 1.3 handshake / certificates / key derivation
  ▼
NGINX QUIC
  │
  │ packet-protection keys
  ▼
NGI541
  │
  │ AES execution
  ▼
QUIC packet data path
```

NGI541 therefore augments the execution path without replacing OpenSSL as the TLS stack.

## TLS 1.3 over TCP

Conventional TLS 1.3 over TCP has a different ownership boundary.

Conceptually:

```text
NGINX
  │
  ▼
OpenSSL TLS
  ├── handshake
  ├── key schedule
  └── record protection
```

TLS record encryption is normally performed inside the TLS implementation rather than directly by NGINX.

A direct NGINX-to-NGI541 substitution is therefore not equivalent to the QUIC integration.

A future TLS 1.3 evaluation is expected to require a TLS-stack integration mechanism such as an OpenSSL provider or another explicitly supported crypto backend.

## Provider integration

A provider-style integration preserves the existing application-to-TLS boundary:

```text
application / NGINX
        │
        ▼
      OpenSSL
        │
        ▼
NGI541 provider/backend
        │
        ▼
cryptographic execution
```

This is attractive for adoption because existing applications may require fewer protocol-specific modifications.

However, the additional abstraction may have a different execution cost from direct integration.

Provider integration is therefore both an adoption mechanism and an experimental variable.

## Experimental comparison

Where technically possible, the project should distinguish:

```text
stock OpenSSL
OpenSSL with NGI541 provider/backend
direct NGI541 integration
```

These configurations answer different questions.

The stock path provides the system baseline.

Provider integration measures the cost and benefit of a lower-friction adoption path.

Direct integration measures the execution model with the protocol stack calling NGI541 explicitly at the data-path boundary.

## Reverse proxy

A TLS reverse proxy is an important integration workload because it introduces independent cryptographic state on both sides of the proxy:

```text
client
  ⇅
downstream TLS
  ⇅
NGINX proxy
  ⇅
upstream TLS
  ⇅
origin
```

The proxy may execute decrypt and encrypt operations for both traffic directions and maintain many simultaneous persistent key contexts.

This makes reverse-proxy evaluation useful for studying:

- concurrency;
- prepared-key reuse;
- cache behavior;
- worker scaling;
- integration overhead.

## Ownership principle

NGI541 should only take ownership of functionality required by its execution role.

Protocol state, PKI, and handshake logic should remain in established protocol implementations unless a future research objective explicitly requires a different boundary.

This separation keeps NGI541 usable as a cryptographic execution backend rather than requiring applications to adopt a replacement TLS or network stack.

See also:

- [`experimental-scope.md`](experimental-scope.md)
- [`benchmark-methodology.md`](benchmark-methodology.md)
- [`topology.md`](topology.md)
