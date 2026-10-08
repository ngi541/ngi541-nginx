#!/bin/bash
set -euo pipefail

NAME="$1"
NGINX="$2"
SIZE="$3"
PER_CLIENT="${4:-5000}"
CLIENTS="${5:-8}"

ABROOT=/tmp/ngi541-nginx-ab
CONFIG="$ABROOT/conf/nginx-4worker.conf"
CURL=/usr/local/opt/curl/bin/curl
WARMUP_PER_CLIENT=50

cleanup() {
    if [[ -n "${PID:-}" ]]; then
        kill "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT

if ! grep -Eq \
    '^[[:space:]]*worker_processes[[:space:]]+4[[:space:]]*;' \
    "$CONFIG"
then
    echo "ERROR: $CONFIG does not configure worker_processes 2"
    exit 1
fi

QUIC_LISTEN=$(
    grep -E \
      '^[[:space:]]*listen[[:space:]].*8443' \
      "$CONFIG" \
    | grep 'quic' \
    | head -1 \
    || true
)

if [[ -z "$QUIC_LISTEN" ]]; then
    echo "ERROR: QUIC listen directive not found"
    exit 1
fi

if [[ "$QUIC_LISTEN" != *reuseport* ]]; then
    echo "ERROR: 4-worker QUIC test requires reuseport"
    echo "current: $QUIC_LISTEN"
    exit 1
fi

"$NGINX" \
    -p "$ABROOT/" \
    -c conf/nginx-4worker.conf \
    >"$ABROOT/logs/${NAME}-4w.stdout.log" 2>&1 &

PID=$!

sleep 0.5

run_clients() {
    local count="$1"
    local phase="$2"
    local failed=0
    local c
    local err

    PIDS=()

    for ((c=1; c<=CLIENTS; c++)); do
        err="/tmp/${NAME}-4w-${SIZE}-${phase}-c${c}.err"
        rm -f "$err"

        "$CURL" \
            --http3-only \
            --tls13-ciphers TLS_AES_128_GCM_SHA256 \
            -k \
            --silent \
            --show-error \
            --fail \
            --fail-early \
            --out-null \
            "https://127.0.0.1:8443/${SIZE}.bin?client=${c}&${phase}=[1-${count}]" \
            2>"$err" &

        PIDS[$c]=$!
    done

    for ((c=1; c<=CLIENTS; c++)); do
        if wait "${PIDS[$c]}"; then
            :
        else
            failed=1
        fi
    done

    if [[ "$failed" -ne 0 ]]; then
        echo "ERROR: one or more curl clients failed"

        for ((c=1; c<=CLIENTS; c++)); do
            err="/tmp/${NAME}-4w-${SIZE}-${phase}-c${c}.err"

            if [[ -s "$err" ]]; then
                echo "===== client $c ====="
                cat "$err"
            fi
        done

        return 1
    fi

    for ((c=1; c<=CLIENTS; c++)); do
        err="/tmp/${NAME}-4w-${SIZE}-${phase}-c${c}.err"

        if [[ -s "$err" ]]; then
            echo "ERROR: unexpected stderr from client $c"
            cat "$err"
            return 1
        fi
    done
}

# Warm both workers / crypto paths before measurement.
run_clients "$WARMUP_PER_CLIENT" "warm"

START=$(python3 -c 'import time; print(time.perf_counter_ns())')

run_clients "$PER_CLIENT" "i"

END=$(python3 -c 'import time; print(time.perf_counter_ns())')

python3 - \
    "$NAME" \
    "$SIZE" \
    "$CLIENTS" \
    "$PER_CLIENT" \
    "$START" \
    "$END" <<'PY'
import sys

name, size, clients, per_client, start, end = sys.argv[1:]

clients = int(clients)
per_client = int(per_client)

count = clients * per_client
seconds = (int(end) - int(start)) / 1e9

payload = 1024 if size == "1k" else 16384

rps = count / seconds
mib_s = count * payload / seconds / (1024 * 1024)

print(
    f"{name:8s} size={size:3s} "
    f"workers=4 "
    f"clients={clients} "
    f"per_client={per_client} "
    f"requests={count} "
    f"time={seconds:.6f}s "
    f"req/s={rps:.2f} "
    f"payload_MiB/s={mib_s:.2f}"
)
PY
