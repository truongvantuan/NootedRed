#!/bin/bash
# VDA preflight: read-only checks that the machine and build are ready for the -NRedVDA boot test.
# Run from the repository root before deploying the kext. No sudo, no GPU/VideoToolbox calls.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAIL=0
WARN=0

pass()  { echo "PASS  $*"; }
fail()  { echo "FAIL  $*"; FAIL=$((FAIL + 1)); }
warn()  { echo "WARN  $*"; WARN=$((WARN + 1)); }

echo "== VDA preflight =="

# --- macOS/Darwin identity: generated data is 15.8.1 (Darwin 24.6) only ---
PRODUCT="$(sw_vers -productVersion 2>/dev/null)"
BUILD="$(sw_vers -buildVersion 2>/dev/null)"
DARWIN="$(uname -r)"
DARWIN_MAJOR="$(echo "${DARWIN}" | cut -d. -f1)"
DARWIN_MINOR="$(echo "${DARWIN}" | cut -d. -f2)"
echo "macOS ${PRODUCT} (${BUILD}), Darwin ${DARWIN}"
if [[ "${DARWIN_MAJOR}" == "24" && "${DARWIN_MINOR}" == "6" ]]; then
    pass "OS/build matches macOS 15.x (Darwin 24.6) Sequoia series"
elif [[ "${DARWIN_MAJOR}" == "23" && "${DARWIN_MINOR}" == "6" ]]; then
    pass "OS/build matches macOS 14.x (Darwin 23.6) Sonoma series (${BUILD})"
elif [[ "${DARWIN_MAJOR}" == "25" && "${DARWIN_MINOR}" == "6" ]]; then
    pass "OS/build matches macOS 26.x (Darwin 25.6) Tahoe series (${BUILD})"
else
    fail "OS/build does not match supported VDA data (macOS 14/15/26 Darwin 23.6/24.6/25.6)"
fi

# --- iGPU identity ---
DISPLAY_INFO="$(system_profiler SPDisplaysDataType 2>/dev/null)"
DEVICE_ID="$(echo "${DISPLAY_INFO}" | sed -n 's/.*Device ID: \(0x[0-9A-Fa-f]*\).*/\1/p' | head -n1)"
CHIP_COUNT="$(echo "${DISPLAY_INFO}" | grep -c 'Chipset Model:' || true)"
echo "iGPU device ID: ${DEVICE_ID:-unknown}; display chips: ${CHIP_COUNT}"
DEV_ID_LOWER="$(echo "${DEVICE_ID}" | tr '[:upper:]' '[:lower:]')"
if [[ "${DEV_ID_LOWER}" == "0x1638" || "${DEV_ID_LOWER}" == "0x15e7" || "${DEV_ID_LOWER}" == "0x1636" || "${DEV_ID_LOWER}" == "0x164c" ]]; then
    pass "iGPU is a supported VCN 2.x target (${DEVICE_ID})"
else
    fail "iGPU is not a supported VCN 2.x target; do not enable -NRedVDA with this data"
fi
if [[ "${CHIP_COUNT}" -gt 1 ]]; then
    warn "more than one display chip found; a dGPU can make the X6000 bridge unsafe (it should refuse, but verify)"
fi

BOOTARGS="$(sysctl -n kern.bootargs 2>/dev/null || true)"

# --- X6000 accelerator: it may be loaded by this experimental bridge, but not preloaded for a dGPU ---
if kextstat 2>/dev/null | grep -q 'com.apple.kext.AMDRadeonX6000 '; then
    if echo "${BOOTARGS:-$(sysctl -n kern.bootargs 2>/dev/null || true)}" | grep -q -- '-NRedVDA'; then
        pass "AMDRadeonX6000 is loaded (expected when -NRedVDA is active)"
    else
        fail "AMDRadeonX6000 is already loaded without -NRedVDA; the VDA bridge must not be enabled"
    fi
else
    pass "AMDRadeonX6000 is not loaded as an accelerator"
fi

# --- X6000 kext must be available in the kernel collection so OSKextLoadKextWithIdentifier can load it ---
if kmutil inspect -S /System/Library/KernelCollections/SystemKernelExtensions.kc --show-extension-info 2>/dev/null \
    | grep -q 'com.apple.kext.AMDRadeonX6000'; then
    pass "com.apple.kext.AMDRadeonX6000 is present in SystemKernelExtensions.kc"
else
    fail "com.apple.kext.AMDRadeonX6000 is not in the system kernel collection"
fi

# --- generated data matches this machine's cache/kernel collection ---
if [[ "${DARWIN_MAJOR}" == "23" ]]; then
    if [[ -f "${ROOT}/NootedRed/VCNKernelData.hpp" && -f "${ROOT}/NootedRed/VDAVADataSonoma.hpp" && -f "${ROOT}/NootedRed/VDAGVADataSonoma.hpp" ]]; then
        pass "Sonoma VDA headers present (VCNKernelData, VDAVADataSonoma, VDAGVADataSonoma)"
    else
        fail "missing Sonoma VDA headers"
    fi
elif [[ "${DARWIN_MAJOR}" == "24" ]]; then
    if [[ -f "${ROOT}/NootedRed/VCNKernelData.hpp" && -f "${ROOT}/NootedRed/VDAVADataSequoia.hpp" && -f "${ROOT}/NootedRed/VDAGVADataSequoia.hpp" ]]; then
        pass "Sequoia VDA headers present (VCNKernelData, VDAVADataSequoia, VDAGVADataSequoia)"
    else
        fail "missing Sequoia VDA headers"
    fi
fi

# --- build artifact (per-branch layout, with the old path as fallback) ---
KEXT=""
BRANCH="$(git -C "${ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -z "${BRANCH}" || "${BRANCH}" == "HEAD" ]]; then
    BRANCH="detached-$(git -C "${ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
fi
BRANCH="$(printf '%s' "${BRANCH}" | sed -E 's/[^A-Za-z0-9._-]+/-/g; s/^-+//; s/-+$//')"
MAIN_ROOT="$(cd "$(git -C "${ROOT}" rev-parse --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd || true)"
for candidate in \
    "${ROOT}/build/branches/${BRANCH}/macosx/x86_64/release/NootedRed.kext" \
    "${ROOT}/build/branches/shared/macosx/x86_64/release/NootedRed.kext" \
    "${ROOT}/build/macosx/x86_64/release/NootedRed.kext" \
    "${MAIN_ROOT}/build/branches/${BRANCH}/macosx/x86_64/release/NootedRed.kext" \
    "${MAIN_ROOT}/build/branches/shared/macosx/x86_64/release/NootedRed.kext" \
    "${MAIN_ROOT}/build/artifacts/${BRANCH}/NootedRed.kext"; do
    if [[ -d "${candidate}" ]]; then KEXT="${candidate}"; break; fi
done
if [[ -z "${KEXT}" ]]; then
    KEXT="$(find "${ROOT}/build" -path '*/macosx/x86_64/release/NootedRed.kext' -type d 2>/dev/null | head -n1)"
fi
if [[ -n "${KEXT}" && -d "${KEXT}" ]]; then
    HASH="$(shasum -a 256 "${KEXT}/Contents/MacOS/NootedRed" | awk '{print $1}')"
    pass "release kext present (SHA-256 ${HASH})"
else
    fail "release kext missing (looked under build/branches/* and build/macosx)"
fi

# --- boot arguments / EFI ---
echo "boot-args: ${BOOTARGS}"
if echo "${BOOTARGS}" | grep -q -- '-NRedVDA'; then
    warn "-NRedVDA is already in boot-args; the next boot will run the experimental path"
else
    pass "-NRedVDA is absent (default-off path; add it only for the experiment)"
fi
if diskutil list 2>/dev/null | grep -q 'EFI NO NAME'; then
    if mount | grep -q '/Volumes/NO NAME'; then
        pass "OpenCore ESP is mounted at '/Volumes/NO NAME'"
    else
        warn "OpenCore ESP exists but is not mounted; run: sudo diskutil mount disk0s1"
    fi
fi

# --- toolchain used by the build ---
if [[ -x /Library/Developer/CommandLineTools/usr/bin/llvm-objdump ]]; then
    pass "CommandLineTools LLVM tools available (use DEVELOPER_DIR=/Library/Developer/CommandLineTools)"
else
    warn "CommandLineTools LLVM tools not found"
fi

echo
if [[ ${FAIL} -eq 0 ]]; then
    echo "PREFLIGHT OK (${WARN} warning(s))"
    exit 0
else
    echo "PREFLIGHT FAILED (${FAIL} failure(s), ${WARN} warning(s))"
    exit 1
fi
