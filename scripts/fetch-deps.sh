#!/usr/bin/env bash

set -euo pipefail


ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSIONS="$ROOT/config/versions.env"

if [[ ! -f "$VERSIONS" ]]; then
    echo "ERROR: missing $VERSIONS" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$VERSIONS"


SRC_DIR="$ROOT/src"
WORK_DIR="$ROOT/work"
DOWNLOAD_DIR="$WORK_DIR/downloads"

NGINX_ARCHIVE="$DOWNLOAD_DIR/nginx-${NGINX_VERSION}.tar.gz"
OPENSSL_ARCHIVE="$DOWNLOAD_DIR/openssl-${OPENSSL_VERSION}.tar.gz"

NGINX_SRC="$SRC_DIR/nginx-${NGINX_VERSION}"
OPENSSL_SRC="$SRC_DIR/openssl-${OPENSSL_VERSION}"
NGINX_TESTS_SRC="$SRC_DIR/nginx-tests"

NGINX_URL="https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz"
OPENSSL_URL="https://github.com/openssl/openssl/releases/download/openssl-${OPENSSL_VERSION}/openssl-${OPENSSL_VERSION}.tar.gz"
NGINX_TESTS_URL="https://github.com/nginx/nginx-tests.git"


fail()
{
    echo "ERROR: $*" >&2
    exit 1
}


sha256_file()
{
    local file="$1"

    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$file" | awk '{print $1}'
        return
    fi

    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file" | awk '{print $1}'
        return
    fi

    fail "neither shasum nor sha256sum is available"
}


verify_sha256()
{
    local file="$1"
    local expected="$2"
    local actual

    actual="$(sha256_file "$file")"

    if [[ "$actual" != "$expected" ]]; then
        echo "SHA256 mismatch:" >&2
        echo "  file:     $file" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        exit 1
    fi

    echo "PASS: SHA256 $(basename "$file")"
}


download()
{
    local url="$1"
    local output="$2"

    if [[ -f "$output" ]]; then
        echo "Using cached $(basename "$output")"
        return
    fi

    echo "Downloading:"
    echo "  $url"

    curl \
        --fail \
        --location \
        --retry 3 \
        --proto '=https' \
        --tlsv1.2 \
        --output "$output.tmp" \
        "$url"

    mv "$output.tmp" "$output"
}


mkdir -p "$SRC_DIR" "$DOWNLOAD_DIR"


if [[ -e "$NGINX_SRC" ||
      -e "$OPENSSL_SRC" ||
      -e "$NGINX_TESTS_SRC" ]]; then

    cat >&2 <<EOF_EXISTS
ERROR: dependency source tree already exists under:

  $SRC_DIR

fetch-deps.sh intentionally refuses to overwrite an existing source tree.

For a clean reproduction run:

  rm -rf "$SRC_DIR"

Cached archives under work/downloads may be kept.
EOF_EXISTS

    exit 1
fi


#
# NGINX
#

download "$NGINX_URL" "$NGINX_ARCHIVE"
verify_sha256 "$NGINX_ARCHIVE" "$NGINX_SHA256"

tar -xzf "$NGINX_ARCHIVE" -C "$SRC_DIR"

[[ -d "$NGINX_SRC" ]] \
    || fail "NGINX extraction did not create $NGINX_SRC"

echo "PASS: NGINX $NGINX_VERSION extracted"


#
# OpenSSL
#

download "$OPENSSL_URL" "$OPENSSL_ARCHIVE"
verify_sha256 "$OPENSSL_ARCHIVE" "$OPENSSL_SHA256"

tar -xzf "$OPENSSL_ARCHIVE" -C "$SRC_DIR"

[[ -d "$OPENSSL_SRC" ]] \
    || fail "OpenSSL extraction did not create $OPENSSL_SRC"

echo "PASS: OpenSSL $OPENSSL_VERSION extracted"


#
# nginx-tests
#

echo "Cloning nginx-tests"

git clone \
    --no-checkout \
    "$NGINX_TESTS_URL" \
    "$NGINX_TESTS_SRC"

git -C "$NGINX_TESTS_SRC" \
    checkout --detach "$NGINX_TESTS_COMMIT"

actual_commit="$(
    git -C "$NGINX_TESTS_SRC" rev-parse HEAD
)"

if [[ "$actual_commit" != "$NGINX_TESTS_COMMIT" ]]; then
    fail "nginx-tests commit mismatch: $actual_commit"
fi

echo "PASS: nginx-tests $actual_commit"


printf '\nDependency acquisition complete:\n'
printf '  NGINX:      %s\n' "$NGINX_SRC"
printf '  OpenSSL:    %s\n' "$OPENSSL_SRC"
printf '  nginx-tests:%s\n' "$NGINX_TESTS_SRC"
