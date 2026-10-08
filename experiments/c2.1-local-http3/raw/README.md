# Raw measurement disclosure

Standalone per-run machine-readable output containing the accepted C2.1 requests-per-second measurements was not preserved.

The forensic audit recovered:

- historical benchmark runners;
- NGINX benchmark configurations;
- exact payload files;
- NGI541 runtime identity;
- NGI541 source-state patch and build metadata;
- NGINX integration provenance;
- auxiliary server logs.

A search of the preserved audit tree and surviving `/tmp/ngi541-nginx-ab` tree did not recover the accepted summary RPS values from the preserved files.

The accepted values in `../processed/summary.csv` are therefore a reconstructed canonical summary from the original benchmark session record, not a re-analysis of preserved per-run raw files.

This limitation is explicit and must remain attached to any publication or project claim based on this local experiment.

Future canonical experiments must preserve per-run raw measurements directly under the experiment directory before derived analysis is performed.
