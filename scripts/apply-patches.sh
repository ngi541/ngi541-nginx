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


#
# Fresh source tree.
#

if patch \
    --dry-run \
    --silent \
    -p1 \
    -d "$NGINX_SRC" \
    < "$PATCH"
then
    patch \
        -p1 \
        -d "$NGINX_SRC" \
        < "$PATCH"

    echo "PASS: NGI541 NGINX patch applied"
    exit 0
fi


#
# Allow build.sh to be executed again when the exact patch
# is already present.
#

if patch \
    --dry-run \
    --silent \
    -R \
    -p1 \
    -d "$NGINX_SRC" \
    < "$PATCH"
then
    echo "PASS: NGI541 NGINX patch already applied"
    exit 0
fi


fail "NGI541 patch cannot be applied cleanly"
