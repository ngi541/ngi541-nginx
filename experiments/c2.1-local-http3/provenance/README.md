# C2.1 provenance

This directory records the provenance boundary for the accepted local HTTP/3 performance evidence.

## What is preserved

The forensic audit preserved enough information to identify:

- the historical NGI541 base source commit;
- the historical dirty working-tree changes;
- the Release/AVX2 build profile;
- the historical NGI541 shared-library fingerprint;
- NGINX and OpenSSL dependency versions;
- the NGINX integration patch identity;
- benchmark runners;
- NGINX benchmark configurations;
- workload payloads.

Selected provenance artifacts were copied from the C2.1 forensic audit bundle and frozen together with this experiment record.

## What is not preserved

Two important objects were not preserved as exact historical artifacts:

1. the final corrected NGINX executable used for the accepted measurements;
2. standalone per-run machine-readable benchmark output containing the accepted RPS values.

The repository therefore does not claim bit-identical replay of the historical benchmark.

## Historical versus canonical source

The historical benchmark was executed from NGI541 version 0.1.1 at base commit:

```text
f783e4cf99aa20d68b64cc893a60c257c02898e6
```

plus uncommitted direct-prepared working-tree changes.

The later frozen C2.1 source identity is:

```text
e78865845aaa033330b00892388d9d5af749d971
```

The canonical commit includes a post-benchmark correctness correction on the invalid prepared-key path. It must therefore not be presented as byte-identical to the benchmark source snapshot.

## Performance-path relevance of the post-benchmark correction

The correction restores the public `NOT_INITIALIZED` error contract for invalid prepared-execution calls.

It does not add an unconditional engine-state check to valid prepared-key execution.

The accepted historical performance result nevertheless remains associated with the historical source snapshot rather than being retroactively relabeled as a run of the later commit.

## Runtime identity

The accepted corrected benchmark phase used the NGI541 Release/AVX2 runtime whose SHA-256 fingerprint is recorded in `runtime-sha256.txt`.

The runtime fingerprint identifies the preserved NGI541 shared-library artifact, not the missing final NGINX executable.
