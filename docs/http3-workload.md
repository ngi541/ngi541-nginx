# HTTP/3 workload execution

The HTTP/3 workload is the first measured workload implemented by the R5 experiment framework.

It preserves the C2.1 experimental concept while replacing the historical `/tmp`-based scripts with a portable schedule-driven execution contract.

## Comparison boundary

The workload compares server-side NGINX variants.

For the current NGI541 integration:

```text
stock
ngi541-direct
```

The HTTP client remains the same across a comparison pair.

The default cipher suite is forced client-side:

```text
TLS_AES_128_GCM_SHA256
```

This selects AES-128-GCM TLS/QUIC packet protection.

The NGI541 direct integration also uses its prepared AES-CTR primitive to implement AES-based QUIC header protection. AES-CTR is an implementation mechanism for the header-protection mask and is not a TLS cipher suite.

## Local topology

The first executor supports the `local` T0 topology:

```text
curl load generator
        ⇅
127.0.0.1
        ⇅
NGINX DUT
```

Client and server share CPU, memory, scheduling, and loopback networking.

Results from this topology must remain classified as local evidence.

The workload ABI is intentionally independent of T0 so later bare-metal and CloudLab execution can retain the same schedule and raw measurement format.

## Measurement interval

Warmup is outside the measured interval.

The measured interval starts immediately before the concurrent measured curl clients are launched and ends after all measured clients exit.

Primary metric:

```text
completed HTTP/3 requests / measured elapsed seconds
```

The framework records elapsed time in integer nanoseconds and derives requests per second from the planned request count only when all clients complete successfully.

## Strict validity

A measured attempt is valid only when all measured curl processes exit successfully and produce no stderr.

Failed attempts remain in raw storage and are never silently removed.

## Runtime isolation

Each attempt gets a fresh runtime directory containing:

```text
bin/
lib/
conf/
html/
logs/
```

The exact sealed executable and optional shared libraries are copied into this directory after SHA-256 verification.

TLS certificate/key material is generated only in the ephemeral runtime area and is not canonical evidence.

Runtime directories are excluded from Git. Raw measurements and logs are retained.
