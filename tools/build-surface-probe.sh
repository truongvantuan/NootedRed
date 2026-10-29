#!/bin/sh
# Build only; the probe reads its own cache and never submits GPU work.
set -eu
NRED_SURFACE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NRED_SURFACE_OUT=${1:-"$NRED_SURFACE_ROOT/build/tools/surface"}
mkdir -p "$NRED_SURFACE_OUT/types/IOKit"
# These metadata headers need only fixed-width UInt types. Avoid user IOKit's
# unrelated legacy MacTypes::wide declaration when compiling the kernel parser.
cat > "$NRED_SURFACE_OUT/types/IOKit/IOTypes.h" <<'TYPES'
#pragma once
#include <cstdint>
using UInt8=uint8_t;
using UInt32=uint32_t;
using UInt64=uint64_t;
TYPES
xcrun clang++ -std=c++23 -O2 -Wall -Wextra -Werror \
  -I"$NRED_SURFACE_OUT/types" -I"$NRED_SURFACE_ROOT/NootedRed" \
  "$NRED_SURFACE_ROOT/tools/surface_probe.cpp" -o "$NRED_SURFACE_OUT/surface_probe"
