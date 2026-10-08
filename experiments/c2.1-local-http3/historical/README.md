# Historical benchmark artifacts

This directory contains byte-preserved historical benchmark artifacts recovered during the C2.1 forensic audit.

The files are preserved as historical artifacts rather than rewritten into the current reusable benchmark framework.

## Preserved configuration

Expected NGINX configuration files:

```text
configs/nginx.conf
configs/nginx-1worker.conf
configs/nginx-2worker.conf
configs/nginx-4worker.conf
```

`nginx.conf` and `nginx-1worker.conf` are byte-identical in the preserved audit.

## Preserved payloads

```text
payloads/1k.bin
payloads/16k.bin
```

The payloads are retained byte-for-byte because they are small and directly define the historical workload objects served by NGINX.

## Preserved runners

```text
runners/run-ngi541-ab.sh
runners/run-ngi541-ab-v2.sh
runners/run-ngi541-ab-2w.sh
runners/run-ngi541-ab-4w.sh
```

The runners are forensic artifacts.

`run-ngi541-ab.sh` is an early exploratory runner with a fixed 2000-request measurement and is not canonical performance evidence.

`run-ngi541-ab-v2.sh` is the later single-client runner. The exact historical invocation line for the accepted 1-worker / 1-client point was not recovered.

The 2-worker and 4-worker runners support explicit client count and requests-per-client parameters, use 50 warm-up requests per client, force `TLS_AES_128_GCM_SHA256` in curl, and measure elapsed time with `time.perf_counter_ns()`.

Exact shell-history invocations for the accepted campaigns were not recovered and must not be reconstructed as if they were preserved.

## Checksums

`SHA256SUMS.txt` records the known byte identities of the preserved runners, configurations, and payloads.

The preserved historical files can be verified with:

```bash
cd experiments/c2.1-local-http3/historical
shasum -a 256 -c SHA256SUMS.txt
```

## Deliberately excluded artifacts

The following audit files are not part of the frozen performance experiment:

- `server.key` — private key material;
- `server.crt` — not required to support the performance claim;
- zero-byte stdout logs;
- zero-byte `direct-check.log`;
- zero-byte `release-check.log`;
- the large NGINX `error.log`, which does not contain the accepted benchmark measurements;
- preserved binary copies that are not the exact final corrected NGINX benchmark executable.

The external forensic audit bundle may retain additional debugging material, but it is not promoted into canonical project evidence.
