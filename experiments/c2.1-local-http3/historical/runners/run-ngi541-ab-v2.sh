#!/bin/bash
set -euo pipefail

NAME="$1"
NGINX="$2"
SIZE="$3"
COUNT="${4:-2000}"

ABROOT=/tmp/ngi541-nginx-ab
CURL=/usr/local/opt/curl/bin/curl

cleanup() {
    if [[ -n "${PID:-}" ]]; then
        kill "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT

"$NGINX" \
    -p "$ABROOT/" \
    -c conf/nginx.conf \
    >"$ABROOT/logs/${NAME}.stdout.log" 2>&1 &

PID=$!

sleep 0.5

# Separate connection used only for warm-up.
"$CURL" \
    --http3-only \
    --tls13-ciphers TLS_AES_128_GCM_SHA256 \
    -k \
    --silent \
    --show-error \
    --fail \
    --fail-early \
    --out-null \
    "https://127.0.0.1:8443/${SIZE}.bin?warm=[1-50]"

START=$(python3 -c 'import time; print(time.perf_counter_ns())')

set +e

"$CURL" \
    --http3-only \
    --tls13-ciphers TLS_AES_128_GCM_SHA256 \
    -k \
    --silent \
    --show-error \
    --fail \
    --fail-early \
    --out-null \
    "https://127.0.0.1:8443/${SIZE}.bin?i=[1-${COUNT}]" \
    2>"/tmp/${NAME}-${SIZE}.curl.err"

RC=$?

set -e

END=$(python3 -c 'import time; print(time.perf_counter_ns())')

if [[ "$RC" -ne 0 ]]; then
    echo "ERROR: curl failed rc=$RC"
    cat "/tmp/${NAME}-${SIZE}.curl.err"
    exit "$RC"
fi

if [[ -s "/tmp/${NAME}-${SIZE}.curl.err" ]]; then
    echo "ERROR: unexpected curl stderr:"
    cat "/tmp/${NAME}-${SIZE}.curl.err"
    exit 1
fi

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
    f"requests={count} "
    f"time={seconds:.6f}s "
    f"req/s={rps:.2f} "
    f"payload_MiB/s={mib_s:.2f}"
)
PY
