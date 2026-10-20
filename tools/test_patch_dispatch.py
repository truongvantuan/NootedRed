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
constexpr bool kGLFixDefaultEnabled = false;
const int kGLDriverPatchSets[] = {0};
constexpr size_t kGLDriverPatchSetCount = 1;
namespace GLFixSemantic { const int kPatches[] = {0}; constexpr size_t kPatchCount = 1; }
class UserPatches {
public:
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
    const int* patchSets = nullptr;
    size_t patchSetCount = 0;
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
    void patchNativePage(const void*, UInt64, void*, bool);
    auto isPatchedPage(const NativePage&, const UInt8*) const -> bool;
    void patchSignaturePage(const void*, UInt64) { if (resolverEnabled) resolverCalls++; }
    bool patchSemanticPage(const void*, void*, bool) {
        if (!semanticEnabled) return false;
        semanticCalls++;
        return semanticResult;
    }
};
void require(bool condition, const char* label) {
    if (!condition) { std::fprintf(stderr, "FAIL: %s\n", label); std::exit(1); }
}
'''

CASES = r'''
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
    std::puts("passed 14 boot-argument cases and 8 production page-dispatch checks");
}
'''


def main():
    source = (ROOT / "NootedRed/UserPatches.cpp").read_text()
    constants = "\n".join(re.findall(r'const char\* const kBootArg\w+\s*=\s*"[^"]+";', source))
    bodies = "\n".join(method(source, signature) for signature in (
        "void UserPatches::init()", "auto UserPatches::isPatchedPage(",
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
