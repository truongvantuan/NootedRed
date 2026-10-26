#!/bin/sh
# Compile probes only; does not submit GPU work.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$ROOT/build/tools"
xcrun clang++ -std=c++17 -fobjc-arc -O1 -Wall -Wextra "$ROOT/tools/video_probe.mm" \
  -framework Foundation -framework VideoToolbox -framework CoreVideo -framework CoreMedia \
  -o "$ROOT/build/tools/video_probe"
xcrun clang++ -std=c++17 -fobjc-arc -O1 -Wall -Wextra "$ROOT/tools/metal_probe.mm" \
  -framework Foundation -framework Metal -o "$ROOT/build/tools/metal_probe"
echo "Built video_probe and metal_probe under $ROOT/build/tools"
