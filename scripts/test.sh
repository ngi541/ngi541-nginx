#!/usr/bin/env bash

set -euo pipefail


ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT/config/versions.env"


NGINX_SRC="$ROOT/src/nginx-${NGINX_VERSION}"
NGINX_TESTS="$ROOT/src/nginx-tests"

NGINX_BINARY="$NGINX_SRC/objs/nginx"
INSTALL_PREFIX="${NGINX_INSTALL_PREFIX:-$ROOT/install/nginx-ngi541}"

CUSTOM_TEST_SOURCE="$ROOT/tests/nginx-tests/n2_ngi541_auth_failure.t"
CUSTOM_TEST_DEST="$NGINX_TESTS/n2_ngi541_auth_failure.t"

LOG_DIR="$ROOT/work/test-results"


fail()
{
    echo "ERROR: $*" >&2
    exit 1
}


run_test()
{
    local name="$1"
    shift

    local log="$LOG_DIR/${name}.log"

    printf '\n===== %s =====\n' "$name"

    if ! TEST_NGINX_BINARY="$NGINX_BINARY" \
         TEST_NGINX_VERBOSE=1 \
         prove -v "$@" \
         2>&1 | tee "$log"
    then
        echo "ERROR: $name failed" >&2
        exit 1
    fi

    grep -q 'Result: PASS' "$log" \
        || fail "$name did not report Result: PASS"

    echo "PASS: $name"
}


mkdir -p "$LOG_DIR"


#
# Structural prerequisites
#

[[ -x "$NGINX_BINARY" ]] \
    || fail "missing NGINX binary: run scripts/build.sh first"

[[ -d "$NGINX_TESTS" ]] \
    || fail "missing nginx-tests: run scripts/fetch-deps.sh first"

[[ -f "$CUSTOM_TEST_SOURCE" ]] \
    || fail "missing custom test: $CUSTOM_TEST_SOURCE"


actual_tests_commit="$(
    git -C "$NGINX_TESTS" rev-parse HEAD
)"

[[ "$actual_tests_commit" == "$NGINX_TESTS_COMMIT" ]] \
    || fail "nginx-tests commit mismatch: $actual_tests_commit"


#
# Ensure the custom test used by the run is byte-identical to the
# version maintained by this integration repository.
#

cp "$CUSTOM_TEST_SOURCE" "$CUSTOM_TEST_DEST"

cmp "$CUSTOM_TEST_SOURCE" "$CUSTOM_TEST_DEST" \
    || fail "custom authentication test copy mismatch"

echo "PASS: custom authentication test installed"


#
# Verify expected NGI541 API references in the NGINX binary.
#

expected_symbols=(
    ngi541_crypto_aead_decrypt_prepared
    ngi541_crypto_aead_encrypt_prepared
    ngi541_crypto_aead_key_create
    ngi541_crypto_aead_key_destroy
    ngi541_crypto_cipher_encrypt_prepared
    ngi541_crypto_cipher_key_create
    ngi541_crypto_cipher_key_destroy
    ngi541_engine_init
)

symbols="$(
    nm -u "$NGINX_BINARY"
)"

for symbol in "${expected_symbols[@]}"; do
    if ! grep -q "$symbol" <<< "$symbols"; then
        fail "missing NGI541 binary reference: $symbol"
    fi
done

echo "PASS: all expected NGI541 binary references present"


#
# Basic binary/configuration gate.
#

printf '\n===== nginx -V =====\n'
"$NGINX_BINARY" -V 2>&1


printf '\n===== nginx -t =====\n'

"$NGINX_BINARY" \
    -t \
    -p "$INSTALL_PREFIX/" \
    -c conf/nginx.conf

echo "PASS: nginx -t"


#
# Targeted functional gates.
#

cd "$NGINX_TESTS"


run_test \
    quic-ciphers \
    ./quic_ciphers.t


run_test \
    h3-headers \
    ./h3_headers.t


run_test \
    quic-key-update \
    ./quic_key_update.t


run_test \
    ngi541-auth-failure \
    ./n2_ngi541_auth_failure.t


#
# Full regression: exactly the pinned h3_* + quic_* baseline.
#

tests=(h3_*.t quic_*.t)

if [[ "${#tests[@]}" -ne 24 ]]; then
    printf 'Selected regression tests:\n' >&2
    printf '  %s\n' "${tests[@]}" >&2

    fail "expected 24 regression files, found ${#tests[@]}"
fi


FULL_LOG="$LOG_DIR/full-regression.log"

printf '\n===== full h3_* + quic_* regression =====\n'
printf 'Files selected: %d\n' "${#tests[@]}"


if ! TEST_NGINX_BINARY="$NGINX_BINARY" \
     TEST_NGINX_VERBOSE=1 \
     prove -v "${tests[@]}" \
     2>&1 | tee "$FULL_LOG"
then
    fail "full regression failed"
fi


grep -q 'All tests successful.' "$FULL_LOG" \
    || fail "full regression did not report all tests successful"

grep -Eq 'Files=24,[[:space:]]+Tests=331,' "$FULL_LOG" \
    || fail "full regression did not report Files=24, Tests=331"

grep -q 'Result: PASS' "$FULL_LOG" \
    || fail "full regression did not report Result: PASS"


printf '\n'
echo "=============================================="
echo "NGI541 NGINX functional validation: PASS"
echo "=============================================="
echo
echo "Targeted tests:"
echo "  quic_ciphers.t                 PASS"
echo "  h3_headers.t                   PASS"
echo "  quic_key_update.t              PASS"
echo "  n2_ngi541_auth_failure.t       PASS"
echo
echo "Full regression:"
echo "  Files:                         24"
echo "  Tests:                         331"
echo "  Failures:                      0"
echo
echo "Logs:"
echo "  $LOG_DIR"
