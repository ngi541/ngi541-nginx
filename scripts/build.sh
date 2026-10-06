#!/usr/bin/env bash

set -euo pipefail


ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT/config/versions.env"


NGINX_SRC="$ROOT/src/nginx-${NGINX_VERSION}"
OPENSSL_SRC="$ROOT/src/openssl-${OPENSSL_VERSION}"

INSTALL_PREFIX="${NGINX_INSTALL_PREFIX:-$ROOT/install/nginx-ngi541}"


fail()
{
    echo "ERROR: $*" >&2
    exit 1
}


#
# NGI541 is intentionally an external installed dependency.
#

if [[ -z "${NGI541_PREFIX:-}" ]]; then
    fail "NGI541_PREFIX is required"
fi

case "$NGI541_PREFIX" in
    /*)
        ;;
    *)
        fail "NGI541_PREFIX must be an absolute path"
        ;;
esac


[[ -f "$NGI541_PREFIX/include/ngi541/engine.h" ]] \
    || fail "missing $NGI541_PREFIX/include/ngi541/engine.h"

[[ -d "$NGI541_PREFIX/lib" ]] \
    || fail "missing $NGI541_PREFIX/lib"


ngi541_library="$(
    find "$NGI541_PREFIX/lib" \
        -maxdepth 1 \
        -name "libngi541_engine*${NGI541_VERSION}*" \
        -print \
        -quit
)"

[[ -n "$ngi541_library" ]] \
    || fail "NGI541 $NGI541_VERSION library not found under $NGI541_PREFIX/lib"


[[ -d "$NGINX_SRC" ]] \
    || fail "missing NGINX source: run scripts/fetch-deps.sh first"

[[ -d "$OPENSSL_SRC" ]] \
    || fail "missing OpenSSL source: run scripts/fetch-deps.sh first"


#
# Preserve the currently validated PCRE2 environment.
#
# It can be overridden explicitly:
#
#   PCRE2_PREFIX=/path/to/pcre2
#

if [[ -z "${PCRE2_PREFIX:-}" ]]; then
    if command -v brew >/dev/null 2>&1; then
        PCRE2_PREFIX="$(brew --prefix pcre2)"
    else
        fail "PCRE2_PREFIX is required when Homebrew is unavailable"
    fi
fi


[[ -d "$PCRE2_PREFIX/include" ]] \
    || fail "missing PCRE2 include directory: $PCRE2_PREFIX/include"

[[ -d "$PCRE2_PREFIX/lib" ]] \
    || fail "missing PCRE2 library directory: $PCRE2_PREFIX/lib"


#
# Apply the exact integration patch.
#

"$ROOT/scripts/apply-patches.sh"


#
# Clean only generated build/install state.
#

rm -rf "$NGINX_SRC/objs"
rm -rf "$INSTALL_PREFIX"


CC_OPT="-O2 -g"
CC_OPT+=" -I$PCRE2_PREFIX/include"
CC_OPT+=" -DNGX_QUIC_NGI541=1"
CC_OPT+=" -I$NGI541_PREFIX/include"

LD_OPT="-L$PCRE2_PREFIX/lib"
LD_OPT+=" -L$NGI541_PREFIX/lib"
LD_OPT+=" -Wl,-rpath,$NGI541_PREFIX/lib"
LD_OPT+=" -lngi541_engine"


printf '\nBuild configuration:\n'
printf '  NGINX_VERSION:       %s\n' "$NGINX_VERSION"
printf '  OPENSSL_VERSION:     %s\n' "$OPENSSL_VERSION"
printf '  NGI541_VERSION:      %s\n' "$NGI541_VERSION"
printf '  NGI541_PREFIX:       %s\n' "$NGI541_PREFIX"
printf '  PCRE2_PREFIX:        %s\n' "$PCRE2_PREFIX"
printf '  INSTALL_PREFIX:      %s\n' "$INSTALL_PREFIX"
printf '  CC_OPT:              %s\n' "$CC_OPT"
printf '  LD_OPT:              %s\n\n' "$LD_OPT"


cd "$NGINX_SRC"


./configure \
    --prefix="$INSTALL_PREFIX" \
    --with-openssl="$OPENSSL_SRC" \
    --with-http_ssl_module \
    --with-http_v3_module \
    --with-debug \
    --with-cc-opt="$CC_OPT" \
    --with-ld-opt="$LD_OPT"


if command -v sysctl >/dev/null 2>&1 \
    && sysctl -n hw.ncpu >/dev/null 2>&1
then
    JOBS="$(sysctl -n hw.ncpu)"

elif command -v getconf >/dev/null 2>&1
then
    JOBS="$(getconf _NPROCESSORS_ONLN)"

else
    JOBS=1
fi


make -j"$JOBS"
make install


printf '\n===== nginx -V =====\n'
"$NGINX_SRC/objs/nginx" -V


printf '\n===== NGI541 symbols =====\n'

nm -u "$NGINX_SRC/objs/nginx" \
    | grep ngi541 \
    | sort


printf '\nPASS: NGINX + NGI541 build complete\n'
printf 'binary: %s\n' "$NGINX_SRC/objs/nginx"
printf 'install: %s\n' "$INSTALL_PREFIX"
