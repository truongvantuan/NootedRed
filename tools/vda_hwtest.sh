#!/bin/bash
# VDA hardware-decode test: run after booting with -NRedVDA.
# Collects the kernel/user-space markers, then decodes small H.264/HEVC clips with VideoToolbox and compares
# the output with software decoding. Does not install kexts or reboot. A GPU hang is possible on a failing
# engine; keep the rollback runbook ready.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d /tmp/vda-hwtest.XXXXXX)" || exit 1
FAIL=0
WARN=0

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; FAIL=$((FAIL + 1)); }
warn() { echo "WARN  $*"; WARN=$((WARN + 1)); }

run_timeout() {
    # macOS has no timeout(1); perl's alarm is enough for a bounded ffmpeg run.
    perl -e 'alarm shift; exec @ARGV' "$@"
}

echo "== VDA hardware test =="
echo "work dir: ${WORK}"
BOOTARGS="$(sysctl -n kern.bootargs 2>/dev/null || true)"
echo "boot-args: ${BOOTARGS}"

if ! echo "${BOOTARGS}" | grep -q -- '-NRedVDA'; then
    fail "-NRedVDA is not in boot-args; boot with it before running the decode test"
    echo "Diagnostics were still collected in ${WORK}; rerun after adding -NRedVDA."
fi

echo
echo "== kernel/user-space markers =="
ioreg -l -w0 -r -n IGPU 2>/dev/null | grep -oE '"NRed[A-Za-z0-9]+"[[:space:]]*=[[:space:]]*[0-9]+' | sort -u | tee "${WORK}/markers.txt" || true
cat "${WORK}/markers.txt" 2>/dev/null || true
BRIDGE_READY=0
if [[ -s "${WORK}/markers.txt" ]]; then
    pass "NRedVDA/NRedVCN ioreg markers present"
else
    fail "no NRedVDA/NRedVCN ioreg markers (bridge did not run)"
fi
BRIDGE_READY=1
for key in NRedVCNX5000ABIValidated NRedVCNX6000ABIValidated NRedVCNNativeLoadReady NRedVCNEngineAllocated; do
    if grep -qE "\"${key}\"[[:space:]]*=[[:space:]]*1" "${WORK}/markers.txt"; then
        pass "${key}=1"
    else
        fail "${key} is not 1"
        BRIDGE_READY=0
    fi
done
if grep -qE '"NRedVCNUserApplied"[[:space:]]*=[[:space:]]*[0-9]+' "${WORK}/markers.txt"; then
    pass "VDA user-space pages were patched (NRedVCNUserApplied)"
else
    warn "NRedVCNUserApplied is absent (VA/AppleGVA pages may not have been validated yet)"
fi

echo
echo "== logs =="
log show --last boot --style compact --info --debug \
    --predicate 'eventMessage CONTAINS "VCN" OR eventMessage CONTAINS "VDA" OR eventMessage CONTAINS "UserPatch"' \
    2>/dev/null >"${WORK}/vda.log" || true
grep -E "ABI|native load|initHardware|engine|patched|failed|mismatch" "${WORK}/vda.log" | tail -n 40 || true
if grep -qiE "panic|gpuRestart|watchdog" "${WORK}/vda.log"; then
    warn "VDA log contains panic/gpuRestart/watchdog text (inspect ${WORK}/vda.log)"
else
    pass "no panic/gpuRestart/watchdog text in the VDA log"
fi

if [[ ${BRIDGE_READY} -ne 1 ]]; then
    warn "kernel VCN bridge is not ready; skipping VideoToolbox decode comparison because a software fallback would produce a misleading pass"
elif ! command -v ffmpeg >/dev/null 2>&1; then
    warn "ffmpeg is not installed; decode tests were skipped"
else
    echo
    echo "== VideoToolbox availability =="
    ffmpeg -hide_banner -hwaccels 2>/dev/null | tee "${WORK}/hwaccels.txt"
    if grep -qi videotoolbox "${WORK}/hwaccels.txt"; then
        pass "ffmpeg advertises VideoToolbox"
    else
        fail "ffmpeg does not advertise VideoToolbox"
    fi

    make_clip() {
        local out="$1"; shift
        run_timeout 120 ffmpeg -hide_banner -loglevel error -y "$@" "${out}" >/dev/null 2>&1
    }
    decode_case() {
        local name="$1" clip="$2"
        local soft="${WORK}/${name}-soft.yuv" hard="${WORK}/${name}-hw.yuv" log="${WORK}/${name}-hw.log"
        echo
        echo "-- ${name} --"
        if ! run_timeout 120 ffmpeg -hide_banner -loglevel error -y -i "${clip}" -f rawvideo -pix_fmt yuv420p \
            "${soft}" >/dev/null 2>&1; then
            fail "${name}: software decode failed"
            return
        fi
        if run_timeout 180 ffmpeg -hide_banner -loglevel verbose -y -hwaccel videotoolbox -i "${clip}" \
            -f rawvideo -pix_fmt yuv420p "${hard}" >"${log}" 2>&1; then
            pass "${name}: hardware decode command completed"
        else
            fail "${name}: VideoToolbox decode failed (see ${log})"
            return
        fi
        if grep -qiE "videotoolbox|VideoToolbox" "${log}"; then
            pass "${name}: log mentions VideoToolbox"
        else
            warn "${name}: no VideoToolbox mention in the decode log"
        fi
        if cmp -s "${soft}" "${hard}"; then
            pass "${name}: hardware output matches software decoding"
        else
            warn "${name}: hardware output differs from software decoding (check YUV/format differences)"
        fi
    }

    if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libx264; then
        make_clip "${WORK}/h264-720p.mp4" -f lavfi -i testsrc2=size=1280x720:rate=30 -t 2 \
            -c:v libx264 -pix_fmt yuv420p
        make_clip "${WORK}/h264-64.mp4" -f lavfi -i testsrc2=size=64x64:rate=30 -t 2 \
            -c:v libx264 -pix_fmt yuv420p
        decode_case "h264-720p" "${WORK}/h264-720p.mp4"
        decode_case "h264-64x64-known-adverse" "${WORK}/h264-64.mp4"
    else
        warn "ffmpeg has no libx264 encoder; H.264 test skipped"
    fi
    if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libx265; then
        make_clip "${WORK}/hevc-720p.mp4" -f lavfi -i testsrc2=size=1280x720:rate=30 -t 2 \
            -c:v libx265 -pix_fmt yuv420p
        decode_case "hevc-720p" "${WORK}/hevc-720p.mp4"
    else
        warn "ffmpeg has no libx265 encoder; HEVC test skipped"
    fi
fi

echo
echo "== GPU reset / watchdog reports (current boot) =="
log show --last boot --style compact \
    --predicate 'eventMessage CONTAINS[c] "gpuRestart"' 2>/dev/null \
    | tail -n 20 | tee "${WORK}/gpu-resets.log" || true
ls -1t /Library/Logs/DiagnosticReports/*gpuRestart* 2>/dev/null | head -n 5 >>"${WORK}/gpu-resets.log" || true
if grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "${WORK}/gpu-resets.log" 2>/dev/null \
    || ls /Library/Logs/DiagnosticReports/*gpuRestart* >/dev/null 2>&1; then
    warn "GPU reset/watchdog reports exist; review ${WORK}/gpu-resets.log"
else
    pass "no GPU reset/watchdog reports in the selected query"
fi

echo
echo "artifacts: ${WORK}"
if [[ ${FAIL} -eq 0 ]]; then
    echo "HW TEST OK (${WARN} warning(s))"
    exit 0
fi
echo "HW TEST FAILED (${FAIL} failure(s), ${WARN} warning(s))"
exit 1
