#!/bin/bash
# Hardware-required native VideoToolbox tests; software fallback cannot count as hardware success.
# Each codec tests three 720p frames, selected hardware session and pixel readback.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "$ROOT/build/tools/video_probe" ]]; then
    echo 'Build probes first: sh tools/build-feature-probes.sh' >&2
    exit 1
fi
sudo -v
exec python3 "$ROOT/tools/verify_weachy_features.py" --exercise-video "$@"
