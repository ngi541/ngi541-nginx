# Config-driven campaigns

R5.6 adds a resumable campaign command for full experiment automation.

```bash
./scripts/experiment.sh campaign \
  --config benchmark/configs/c2.2-local-http3.json
```

A campaign definition is a version-controlled research artifact. It contains the fixed workload parameters, an explicit ordered condition matrix, repetitions, comparison mode, exact runtime artifact SHA-256 values, and source requirements.

## Lifecycle

The campaign command drives the existing lifecycle rather than bypassing it:

```text
create
  -> plan
  -> prepare
  -> seal
  -> validate
  -> execute
  -> validate
  -> analyze
  -> COMPLETE
```

Every underlying artifact remains the same artifact produced by the manual commands. The orchestrator only selects the next legal stage.

## Resume semantics

The normalized campaign definition is hashed with SHA-256 and snapshotted as `config/campaign.json` inside the experiment. Re-running the same command searches for an experiment with the same campaign name and definition hash.

- exactly one incomplete match: resume it;
- an exact COMPLETE match: validate it and return without creating a duplicate;
- multiple incomplete matches: fail and require `--experiment-id`;
- an incomplete experiment with the same name but a different definition: fail to prevent silent config drift;
- `--new`: intentionally create a new instance of the same campaign.

Examples:

```bash
# Start or automatically resume.
./scripts/experiment.sh campaign \
  --config benchmark/configs/c2.2-local-http3.json

# Resume an exact experiment explicitly.
./scripts/experiment.sh campaign \
  --config benchmark/configs/c2.2-local-http3.json \
  --experiment-id http3-local-20261009T050000Z-aabbcc

# Intentionally repeat a completed campaign.
./scripts/experiment.sh campaign \
  --config benchmark/configs/c2.2-local-http3.json \
  --new
```

If the user interrupts execution, the HTTP/3 executor transitions `RUNNING -> ABORTED`. The next campaign invocation resumes the immutable schedule and skips runs with an already valid attempt. Failed attempts remain append-only raw evidence.

A run failure is not retried automatically inside the same invocation. The campaign stops for inspection. A later explicit campaign invocation resumes from the recorded FAILED stage, preserving the anti-selection-bias rule.

## Framework identity after sealing

For an active sealed campaign, resume is refused if the current `ngi541-nginx` Git commit differs from the framework commit sealed in `manifest.json`. This prevents a campaign from silently executing or analyzing with a different framework implementation.

## Explicit conditions

`experiment.conditions` is an ordered list of exact workload conditions, not a Cartesian product. Fixed parameters live in `experiment.parameters`. A parameter name may not appear in both places.

For C2.2:

```text
16 KiB  1w/1c
16 KiB  2w/8c
16 KiB  2w/16c
16 KiB  4w/16c
16 KiB  4w/32c
 1 KiB  2w/16c
```

With 10 repetitions and two paired variants this resolves to exactly 120 scheduled runs.

## Runtime identity

Every configured executable/shared library has an expected SHA-256. The campaign verifies it before preparation or resumed execution. The regular preparation provenance then records the same hash in the experiment.
