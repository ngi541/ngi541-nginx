#!/usr/bin/env bash

set -euo pipefail


ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT/integration/versions/versions.env"


NGINX_SRC="$ROOT/src/nginx-${NGINX_VERSION}"
PATCH="$ROOT/integration/patches/nginx-${NGINX_VERSION}/0001-ngi541-quic-crypto.patch"


fail()
{
    echo "ERROR: $*" >&2
    exit 1
}


[[ -d "$NGINX_SRC" ]] \
    || fail "missing NGINX source tree: $NGINX_SRC"

[[ -f "$PATCH" ]] \
    || fail "missing patch: $PATCH"


if patch \
    --dry-run \
    --batch \
    --forward \
    -p1 \
    -d "$NGINX_SRC" \
    < "$PATCH" \
    >/dev/null 2>&1
then
    patch \
        --batch \
        --forward \
        -p1 \
        -d "$NGINX_SRC" \
        < "$PATCH"

    echo "PASS: NGINX integration patch applied"

elif patch \
    --dry-run \
    --batch \
    --reverse \
    -p1 \
    -d "$NGINX_SRC" \
    < "$PATCH" \
    >/dev/null 2>&1
then
    echo "PASS: NGINX integration patch already applied"

else
    fail \
        "NGINX integration patch neither applies cleanly nor matches the already-applied state"
fi