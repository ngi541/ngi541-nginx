#!/bin/bash
set -euo pipefail

NAME="$1"
NGINX="$2"
SIZE="$3"
COUNT=2000

ABROOT=/tmp/ngi541-nginx-ab
CURL=/usr/local/opt/curl/bin/curl
CONF="/tmp/ngi541-${SIZE}-${COUNT}.conf"

"$NGINX" \
  -p "$ABROOT/" \
  -c conf/nginx.conf \
  >"$ABROOT/logs/${NAME}.stdout.log" 2>&1 &

PID=$!

cleanup() {
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 0.5

# Warm-up
for i in $(seq 1 20); do
    "$CURL" \
      --http3-only \
      --tls13-ciphers TLS_AES_128_GCM_SHA256 \
      -k -sS \
      -o /dev/null \
      "https://127.0.0.1:8443/${SIZE}.bin"
done

START=$(python3 -c 'import time; print(time.perf_counter_ns())')

"$CURL" \
  --config "$CONF" \
  --http3-only \
  --tls13-ciphers TLS_AES_128_GCM_SHA256 \
  -k -sS \
  -o /dev/null

END=$(python3 -c 'import time; print(time.perf_counter_ns())')

python3 - "$NAME" "$SIZE" "$COUNT" "$START" "$END" <<'PY'
import sys

name, size, count, start, end = sys.argv[1:]
count = int(count)
seconds = (int(end) - int(start)) / 1e9
payload = 1024 if size == "1k" else 16384

rps = count / seconds
mib_s = count * payload / seconds / (1024 * 1024)

print(
    f"{name:8s} size={size:3s} "
    f"time={seconds:.6f}s "
    f"req/s={rps:.2f} "
    f"payload_MiB/s={mib_s:.2f}"
)
PY
