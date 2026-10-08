# HTTP/3 workload adapter

This adapter executes the R5 experiment schedule against NGINX HTTP/3 variants.

## Execution model

For every scheduled run the adapter:

1. selects the sealed variant runtime binding;
2. verifies the executable and library SHA-256 fingerprints;
3. copies those exact artifacts into an ephemeral runtime directory;
4. copies the deterministic payload selected by the run;
5. generates a run-specific NGINX configuration;
6. generates an ephemeral one-day self-signed TLS certificate;
7. validates the NGINX configuration;
8. starts NGINX in the foreground;
9. probes HTTP/3 readiness;
10. performs concurrent warmup;
11. executes concurrent measured curl clients;
12. writes `measurement.json`;
13. preserves client/server logs;
14. shuts NGINX down;
15. continues to the next immutable schedule entry.

No measured value exists only in terminal output.

## Defaults

Unless explicitly overridden in the experiment request:

```text
payload_bytes: [16384]
workers: [1]
clients: [1]
requests_per_client: 5000
warmup_requests_per_client: 50
cipher_suite: TLS_AES_128_GCM_SHA256
server_host: 127.0.0.1
server_port: 8443
worker_connections: 4096
keepalive_requests: 20000
startup_timeout_seconds: 10
client_timeout_seconds: 60
```

For short framework smoke tests, explicitly reduce `requests_per_client`, warmup, clients, and repetitions.

## Runtime bindings

Every variant must be bound during `prepare`:

```bash
--binary stock=/path/to/stock/nginx
--binary ngi541-direct=/path/to/ngi541/nginx
```

The name before `=` must exactly match the variant ID.

Shared libraries required by a variant are supplied before sealing:

```bash
--runtime-library ngi541-direct=/path/to/libngi541_engine.dylib
```

The option may be repeated when the loader needs multiple versioned library files.

All runtime artifacts must be located below the repository directory or its parent so the sealed record can use a portable relative location.

At execution time each artifact is hashed again before and after copying into the ephemeral runtime directory.

## Payloads

Payloads are generated during preparation as zero-filled deterministic files.

This intentionally reproduces the historical C2.1 payload identities for the 1 KiB and 16 KiB cases:

```text
1024 bytes:
5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef

16384 bytes:
4fe7b59af6de3b665b67788cc2f99892ab827efae3a467342b3bb4e3bc8e5bfe
```

Payload identities are recorded in:

```text
execution/workload/manifest.json
```

## Raw output

Each attempt produces:

```text
raw/runs/run-XXXX/attempt-YY/
├── measurement.json
├── nginx.conf
├── nginx-test.stdout.log
├── nginx-test.stderr.log
├── server.stdout.log
├── server.stderr.log
├── stdout.log
├── stderr.log
├── probe/
├── warmup/
└── measured/
```

`stdout.log` and `stderr.log` are aggregated measured-client logs. Per-client logs are retained as well.

## Failure semantics

The executor is fail-fast.

A failed measured run:

```text
RUNNING -> FAILED
```

The invalid attempt remains in raw storage.

Running `execute` again resumes the immutable schedule, skips already valid runs, and creates `attempt-02` for the failed run.

User interruption transitions:

```text
RUNNING -> ABORTED
```

and the same `execute` command resumes later.

## End state

R5.4 deliberately ends successful workload execution at:

```text
ANALYZING
```

R5.5 will consume the raw measurements, select valid attempts, compute statistical summaries, generate dependency-free SVG figures, and transition the experiment to `COMPLETE`.
