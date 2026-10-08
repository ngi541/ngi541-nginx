# Experiment framework core

The R5 framework provides a portable, standard-library-only lifecycle for reproducible NGI541 network-data-path experiments.

## Implemented through R5.4

Current functionality includes:

```text
create
plan
prepare
seal
execute
status
validate
```

R5.4 adds the first measured workload adapter: NGINX HTTP/3.

The successful lifecycle is now:

```text
CREATED
  ↓
PREPARING
  ↓ plan
PREPARING
  ↓ prepare
PREPARING
  ↓ seal
READY
  ↓ execute
RUNNING
  ↓ all scheduled runs valid
ANALYZING
```

R5.5 will implement generic statistical analysis, CSV/JSON summaries, dependency-free SVG rendering, generated result README content, and the `ANALYZING -> COMPLETE` transition.

## HTTP/3 example

Create a small smoke experiment:

```bash
./scripts/experiment.sh create \
  --workload http3 \
  --environment local \
  --variant stock \
  --variant ngi541-direct \
  --repetitions 1 \
  --param 'payload_bytes=[16384]' \
  --param 'workers=[1]' \
  --param 'clients=[2]' \
  --param 'requests_per_client=100' \
  --param 'warmup_requests_per_client=5'
```

Plan:

```bash
./scripts/experiment.sh plan <experiment-id>
```

Prepare with exact runtime artifacts:

```bash
./scripts/experiment.sh prepare <experiment-id> \
  --binary stock=/path/to/stock/nginx \
  --binary ngi541-direct=/path/to/ngi541/nginx \
  --runtime-library ngi541-direct=/path/to/libngi541_engine.dylib
```

Repeat `--runtime-library` if the runtime loader needs several versioned library files.

Seal:

```bash
./scripts/experiment.sh seal <experiment-id>
```

Execute:

```bash
./scripts/experiment.sh execute <experiment-id>
```

Every schedule entry produces an append-only raw measurement attempt. A successful R5.4 execution ends in `ANALYZING`.

## Runtime artifact rule

Variant runtime paths are provided only during preparation.

The sealed experiment stores relative artifact locations and SHA-256 identities.

Execution re-verifies hashes before copying those artifacts into an ephemeral per-attempt runtime directory.

This prevents a later rebuild at the same filesystem path from silently changing the runtime under test.

## Dependencies

Core framework:

```text
Python 3 standard library
Git
```

HTTP/3 workload additionally requires:

```text
NGINX with --with-http_v3_module
curl with --http3-only, --tls13-ciphers, and --out-null
OpenSSL-compatible certificate generation command
```

No NumPy, pandas, matplotlib, PyYAML, or JSON-Schema runtime package is required.
