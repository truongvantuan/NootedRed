#!/usr/bin/env python3
"""Compile and execute the production option/dispatch methods with kernel services stubbed.

This tests real UserPatches.cpp bodies, not a Python copy of the branching logic. It exercises boot-arg
precedence, exact-page priority, ready/unready VDA pages, resolver-only QA, and semantic/resolver order.
It does not load a kext or access the GPU.
"""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def method(source, signature):
    start = source.index(signature)
    body = source.index("{", start)
    depth = 1
    end = body + 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


SHIM = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
using UInt8 = uint8_t;
using UInt32 = uint32_t;
using UInt64 = uint64_t;
using SInt32 = int32_t;
constexpr int KERN_SUCCESS = 0;
#define SYSLOG(...) do {} while (0)
#define DBGLOG(...) do {} while (0)
struct KernelPatcher { static constexpr int kernelWriteLock = 0; };
struct MachInfo { static int setKernelWriting(bool, int) { return KERN_SUCCESS; } };
struct NRed {
    UInt32 lastValue = 0;
    static NRed& singleton() { static NRed n; return n; }
    void setProp32(const char*, UInt32 value) { lastValue = value; }
};
struct VCNBridge {
    bool ready = true;
    static VCNBridge& singleton() { static VCNBridge v; return v; }
    bool loadReady() const { return ready; }
};
SInt32 OSIncrementAtomic(SInt32* value) { return (*value)++; }
const char* args = "";
bool checkKernelArgument(const char* arg) {
    return (std::string(" ") + args + " ").find(std::string(" ") + arg + " ") != std::string::npos;
}
namespace PenguinWizardry {
struct KernelVersion {
    UInt32 maj, min;
    constexpr KernelVersion(UInt32 a, UInt32 b) : maj(a), min(b) {}
    UInt32 major() const { return maj; }
    UInt32 minor() const { return min; }
    bool operator<(const KernelVersion& b) const { return maj < b.maj || (maj == b.maj && min < b.min); }
    bool operator>(const KernelVersion& b) const { return b < *this; }
};
}
enum class KernelVersion { Sonoma = 23, Sequoia = 24, Tahoe = 25 };
PenguinWizardry::KernelVersion version(23, 6);
auto currentKernelVersion() { return version; }
auto getKernelVersion() { return static_cast<KernelVersion>(version.major()); }
constexpr bool kGLFixDefaultEnabled = false;
const int kGLDriverPatches_Sonoma[] = {23}, kGLDriverPatches_Sequoia[] = {24}, kGLDriverPatches_Tahoe[] = {25};
constexpr size_t kGLDriverPatchCount_Sonoma = 1, kGLDriverPatchCount_Sequoia = 1, kGLDriverPatchCount_Tahoe = 1;
const int kResolverSignatures[] = {24}, kResolverSignatures_Sonoma[] = {23};
constexpr size_t kResolverSignatureCount = 1, kResolverSignatureCount_Sonoma = 1;
namespace GLFixSemantic { const int kPatches[] = {0}; constexpr size_t kPatchCount = 1; }
class UserPatches {
public:
    using ApuMask = UInt8;
    static constexpr ApuMask kApuAll = 0x3F;
    struct PatchSet {
        const char* name;
        PenguinWizardry::KernelVersion minVersion, maxVersion;
        ApuMask apus;
        const int* patches;
        size_t count;
        const int* signatures;
        size_t signatureCount;
    };
    static constexpr size_t kPageSize = 4096;
    struct NativeSite { size_t offset; const UInt8* find; const UInt8* replace; size_t size; };
    struct NativePage {
        const UInt8* image = nullptr;
        UInt64 head = 0;
        NativeSite sites[16]{};
        size_t siteCount = 0;
        bool vda = false;
    };
    const int* patches = nullptr;
    size_t patchCount = 0;
    const PatchSet* patchSets = nullptr;
    size_t patchSetCount = 0;
    const int* signatures = nullptr;
    size_t signatureCount = 0, signatureApplied[8]{};
    const int* semanticPatches = nullptr;
    size_t semanticPatchCount = 0;
    NativePage nativePages[1]{};
    size_t nativePageCount = 0;
    SInt32 vdaAppliedCount = 0;
    bool enabled = false, vdaEnabled = false;
    bool resolverOnly = false, resolverEnabled = false;
    bool semanticEnabled = false, semanticMTLEnabled = false, semanticResult = false;
    int resolverCalls = 0, semanticCalls = 0;
    void init();
    void selectPatchSet();
    ApuMask currentApuMask() const { return kApuAll; }
    void patchNativePage(const void*, UInt64, void*, bool);
    auto isPatchedPage(const NativePage&, const UInt8*) const -> bool;
    void patchSignaturePage(const void*, UInt64) { if (resolverEnabled) resolverCalls++; }
    bool patchSemanticPage(const void*, void*, bool) {
        if (!semanticEnabled) return false;
        semanticCalls++;
        return semanticResult;
    }
};
const UserPatches::PatchSet kGLDriverPatchSets[] = {
    {"Sonoma", {23, 0}, {23, 99}, UserPatches::kApuAll, kGLDriverPatches_Sonoma, 1, kResolverSignatures_Sonoma, 1},
    {"Sequoia", {24, 6}, {24, 6}, UserPatches::kApuAll, kGLDriverPatches_Sequoia, 1, kResolverSignatures, 1},
    {"Tahoe", {25, 6}, {25, 6}, UserPatches::kApuAll, kGLDriverPatches_Tahoe, 1, nullptr, 0},
};
constexpr size_t kGLDriverPatchSetCount = 3;
void require(bool condition, const char* label) {
    if (!condition) { std::fprintf(stderr, "FAIL: %s\n", label); std::exit(1); }
}
'''

CASES = r'''
void selection(const char* input, UInt32 major, UInt32 minor, bool semantic, bool metal, const int* patches) {
    args = input;
    version = {major, minor};
    UserPatches p;
    p.init();
    p.selectPatchSet();
    require(p.semanticEnabled == semantic && p.semanticMTLEnabled == metal && p.patches == patches, input);
}
void options(const char* input, bool gl, bool vda, bool resolver, bool semantic, bool metal, bool qa) {
    args = input;
    UserPatches p;
    p.init();
    require(p.enabled == gl && p.vdaEnabled == vda && p.resolverEnabled == resolver
            && p.semanticEnabled == semantic && p.semanticMTLEnabled == metal && p.resolverOnly == qa,
            input);
}
int main() {
    options("", false, false, false, false, false, false);
    options("-NRedGLFix", true, false, true, true, false, false);
    options("-NRedGLFix -NRedGLFixOff", false, false, false, false, false, false);
    options("-NRedGLFix -NRedGLFixResolveOff", true, false, false, true, false, false);
    options("-NRedGLFix -NRedGLFixNoResolve -NRedGLFixSemanticOff", true, false, false, false, false, false);
    options("-NRedGLFix -NRedGLFixSemanticMTL", true, false, true, true, true, false);
    options("-NRedGLFix -NRedGLFixSemanticMTL -NRedGLFixSemanticOff", true, false, true, false, false, false);
    options("-NRedGLFix -NRedGLFixResolveOnly", true, false, true, true, false, true);
    options("-NRedGLFix -NRedGLFixResolveOnly -NRedGLFixResolveOff", true, false, false, true, false, false);
    options("-NRedVDA", false, true, false, false, false, false);
    options("-NRedAVC", false, true, false, false, false, false);
    options("-NRedGLFix -NRedAVC", true, true, true, true, false, false);
    options("-NRedGLFix -NRedGLFixOff -NRedVDA", false, true, false, false, false, false);
    options("-NRedGLFixResolve -NRedGLFixSemanticMTL", false, false, false, false, false, false);

    selection("-NRedGLFix", 23, 6, false, false, kGLDriverPatches_Sonoma);
    selection("-NRedGLFix", 24, 6, false, false, kGLDriverPatches_Sequoia);
    selection("-NRedGLFix", 25, 6, false, false, kGLDriverPatches_Tahoe);
    selection("-NRedGLFix", 24, 7, true, true, kGLDriverPatches_Sequoia);
    selection("-NRedGLFix", 25, 7, true, true, kGLDriverPatches_Tahoe);
    selection("-NRedGLFix -NRedGLFixSemanticMTL", 23, 6, true, true, kGLDriverPatches_Sonoma);
    selection("-NRedGLFix -NRedGLFixSemanticMTL -NRedGLFixSemanticOff", 23, 6, false, false, kGLDriverPatches_Sonoma);
    selection("-NRedGLFix -NRedGLFixSemanticOff", 24, 7, false, false, kGLDriverPatches_Sequoia);
    selection("-NRedGLFix -NRedGLFixResolveOff", 23, 6, false, false, kGLDriverPatches_Sonoma);
    selection("-NRedVDA", 24, 7, false, false, kGLDriverPatches_Sequoia);

    UInt8 stock[4096], data[4096], find = 0x11, replace = 0x22;
    std::memset(stock, 0xA5, sizeof(stock));
    stock[32] = find;
    auto fixture = [&]() {
        UserPatches p;
        p.nativePageCount = 1;
        auto& page = p.nativePages[0];
        page.image = stock;
        std::memcpy(&page.head, stock, sizeof(page.head));
        page.siteCount = 1;
        page.sites[0] = {32, &find, &replace, 1};
        p.resolverEnabled = p.semanticEnabled = true;
        std::memcpy(data, stock, sizeof(data));
        return p;
    };
    {
        auto p = fixture();
        p.resolverOnly = true;
        p.nativePages[0].vda = true;
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(data[32] == replace && p.vdaAppliedCount == 1 && !p.resolverCalls && !p.semanticCalls,
                "GL resolver QA preserves exact ready VDA pages");
    }
    {
        auto p = fixture();
        p.resolverOnly = true;
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(data[32] == find && p.resolverCalls == 1 && !p.semanticCalls,
                "GL resolver QA skips exact GL and semantic matching");
    }
    {
        auto p = fixture();
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(data[32] == replace && !p.resolverCalls && !p.semanticCalls,
                "exact GL pages take priority over both fallback mechanisms");
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(!p.resolverCalls && !p.semanticCalls, "already-patched exact pages are not rescanned");
    }
    {
        auto p = fixture();
        data[0] ^= 1;
        p.semanticResult = true;
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(p.semanticCalls == 1 && !p.resolverCalls, "semantic match takes priority over resolver");
    }
    {
        auto p = fixture();
        data[0] ^= 1;
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(p.semanticCalls == 1 && p.resolverCalls == 1, "unmatched semantic page reaches resolver");
    }
    {
        auto p = fixture();
        p.nativePages[0].vda = true;
        p.resolverEnabled = p.semanticEnabled = false;
        VCNBridge::singleton().ready = false;
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(data[32] == find && !p.vdaAppliedCount && !p.resolverCalls && !p.semanticCalls,
                "unready VCN bridge leaves video page untouched");
        VCNBridge::singleton().ready = true;
        p.patchNativePage(data, 0xE000, nullptr, false);
        require(data[32] == replace && p.vdaAppliedCount == 1,
                "video-only mode works with all graphics fallbacks disabled");
    }
    std::puts("passed 14 boot-argument, 10 semantic selection and 8 production page-dispatch checks");
}
'''


def main():
    source = (ROOT / "NootedRed/UserPatches.cpp").read_text()
    constants = "\n".join(re.findall(r'const char\* const kBootArg\w+\s*=\s*"[^"]+";', source))
    bodies = "\n".join(method(source, signature) for signature in (
        "void UserPatches::init()", "void UserPatches::selectPatchSet()", "auto UserPatches::isPatchedPage(",
        "void UserPatches::patchNativePage("))
    with tempfile.TemporaryDirectory(prefix="nred-dispatch-") as directory:
        path = Path(directory)
        (path / "test.cpp").write_text(SHIM + constants + bodies + CASES)
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Wno-unused-parameter",
                                  str(path / "test.cpp"), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True)


if __name__ == "__main__":
    main()
