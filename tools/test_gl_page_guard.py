#!/usr/bin/env python3
"""Execute production GL matching against the NotificationCenter collision and real driver tables.

No GPU access. The captured instruction context is sufficient to reproduce the old short-site
false match; full Apple application pages are not distributed. Positive tests use repository driver
fixtures and execute the same C++ methods compiled into the kext.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from test_gl_semantic_data import load_arrays
from test_patch_dispatch import SHIM, method

ROOT = Path(__file__).resolve().parents[1]

CASES = r'''
int main() {
    const char* driver = "AMDRadeonX5000GLDriver";
    auto vnode = [](const char* name) { return const_cast<char*>(name); };
    UserPatches matcher;
    for (const char* name : {"NotificationCenter", "prefixAMDRadeonX5000GLDriver",
                             "AMDRadeonX5000GLDriver.backup", "AMDRadeonX5000GLDriver.bundle", ""}) {
        require(!matcher.isGLDriverVnode(vnode(name)), "only the exact GL executable name qualifies");
    }
    require(!matcher.isGLDriverVnode(nullptr), "unknown vnode must fail closed");
    require(matcher.isGLDriverVnode(vnode(driver)), "real driver name accepted");

    const UInt8 find[] = {0x83, 0xe0, 0xfe}, replace[] = {0x83, 0xc8, 0x01};
    UInt8 data[4096];
    auto fixture = [&]() {
        UserPatches p;
        p.nativePageCount = 1;
        auto& page = p.nativePages[0];
        page.image = driverPage;
        std::memcpy(&page.head, driverPage, sizeof(page.head));
        page.siteCount = 1;
        page.sites[0] = {0x160, find, replace, sizeof(find)};
        page.glDriver = true;
        std::memcpy(data, driverPage, sizeof(data));
        return p;
    };
    for (bool changedPage : {false, true}) {
        for (const char* target : {driver, "NotificationCenter", "AMDRadeonX5000GLDriver.copy"}) {
            auto p = fixture();
            if (changedPage) data[0] ^= 1; // outside site context: legitimate nearby driver build
            p.patchNativePage(data, 0x8000, vnode(target), false);
            const bool changed = std::memcmp(data + 0x160, replace, sizeof(replace)) == 0;
            require(changed == (target == driver && !changedPage), "legacy GL path requires full page and driver identity");
        }
    }
    for (bool changedPage : {false, true}) {
        auto p = fixture();
        p.nativePages[0].exactOnly = true;
        if (changedPage) data[0] ^= 1;
        p.patchNativePage(data, 0x8000, vnode(driver), false);
        require((std::memcmp(data + 0x160, replace, sizeof(replace)) == 0) == !changedPage,
                "exact-only function pages reject nearby-build contextual fallback");
    }
    for (bool changedPage : {false, true}) {
        for (const char* target : {driver, "NotificationCenter"}) {
            auto p = fixture();auto& page=p.nativePages[0];
            page.image=budgetPage;std::memcpy(&page.head,budgetPage,sizeof(page.head));
            page.sites[0]={0x6f9,budgetFind,budgetReplace,sizeof(budgetFind)};page.exactOnly=true;
            std::memcpy(data,budgetPage,sizeof(data));if(changedPage)data[0]^=1;
            p.patchNativePage(data,0x5000,vnode(target),false);
            require((std::memcmp(data+0x6f9,budgetReplace,sizeof(budgetReplace))==0)==(!changedPage&&target==driver),
                    "actual budget function patches only the exact driver page");
        }
    }
    // The observed 24H32 NotificationCenter context around image offset 0x231160.
    for (bool changedPage : {false,true}) for (bool ready : {false,true}) {
        UserPatches p;p.nativePageCount=1;auto& page=p.nativePages[0];
        page.image=vaPitchPage;std::memcpy(&page.head,vaPitchPage,sizeof(page.head));
        page.vda=true;page.exactOnly=true;page.siteCount=1;
        page.sites[0]={0xaf5,vaPitchFind,vaPitchReplace,sizeof(vaPitchFind)};
        std::memcpy(data,vaPitchPage,sizeof(data));if(changedPage)data[0]^=1;
        VCNBridge::singleton().ready=ready;
        p.patchNativePage(data,0x30864c000,vnode("dyld_shared_cache_x86_64h.02"),true);
        require((std::memcmp(data+0xaf5,vaPitchReplace,sizeof(vaPitchReplace))==0)==(!changedPage&&ready),
                "VA pitch replacement requires exact full page and ready VCN bridge");
    }
    VCNBridge::singleton().ready=true;
    const UInt8 notificationContext[] = {
        0x88,0x99,0,0,0,0x0f,0x84,0x91,0,0,0,0x48,0x8d,0x46,1,0x48,
        0x83,0xe0,0xfe,0x48,0xff,0xce,0x66,0x48,0x0f,0x6e,0xc6,0x66,
        0x0f,0x70,0xc0,0x44,0x66,0x0f,0x38
    };
    for (const char* target : {"NotificationCenter", driver}) {
        auto p = fixture();
        std::memset(data, 0, sizeof(data));
        std::memcpy(data + 0x150, notificationContext, sizeof(notificationContext));
        require(std::memcmp(data + 0x160, find, sizeof(find)) == 0,
                "fixture reproduces upstream's three-byte site match");
        UInt8 before[4096]; std::memcpy(before, data, sizeof(data));
        p.patchNativePage(data, 0x231000, vnode(target), false);
        require(std::memcmp(before, data, sizeof(data)) == 0,
                "NotificationCenter loop is unchanged, even under a mislabeled vnode");
    }

    // Resolver-only path must enforce the same identity even with a complete matching context.
    const UInt8 mask[32] = {255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
                            255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255};
    const UserPatches::SignaturePatch sig{resolverContext, mask, 32, 16, replace, 3, 0, 1, 0x8000, true};
    for (const char* target : {driver, "NotificationCenter", "AMDRadeonX5000GLDriver.copy"}) {
        UserPatches p;
        p.signatures = &sig; p.signatureCount = 1; p.resolverEnabled = p.resolverOnly = true;
        std::memset(data, 0, sizeof(data));
        std::memcpy(data + 0x150, resolverContext, 32);
        p.patchNativePage(data, 0x8000, vnode(target), false);
        const bool changed = std::memcmp(data + 0x160, replace, 3) == 0;
        require(changed == (target == driver), "resolver-only GL patches require driver identity");
    }

    // Gate 0 applies even to a byte-for-byte page collision in an unrelated vnode.
    for (const char* name : {static_cast<const char*>(nullptr), "", "NotificationCenter", "dyld",
                             "dyld_shared_cache_x86_6", "fake_dyld_shared_cache_x86_64h",
                             "AMDRadeonVADriver2", "AppleGVA", "dyld_shared_cache_x86_64h.02"}) {
        auto p=fixture();p.nativePages[0].glDriver=false;p.nativePages[0].vda=true;
        const bool allowed=name && (!std::strcmp(name,"AMDRadeonVADriver2") || !std::strcmp(name,"AppleGVA")
                                     || !std::strcmp(name,"dyld_shared_cache_x86_64h.02"));
        p.patchNativePage(data,0x8000,vnode(name),true);
        require((std::memcmp(data+0x160,replace,sizeof(replace))==0)==allowed,
                "Gate 0 rejects null/irrelevant/substring vnodes even on full-page collision");
    }
    for(bool blend : {false,true}) {
        auto p=fixture();p.nativePages[0].glDriver=false;p.legacyBlendEnabled=blend;
        p.patchNativePage(data,0x8000,vnode("dyld_shared_cache_x86_64h.02"),true);
        require((std::memcmp(data+0x160,replace,sizeof(replace))==0)==blend,
                "blend opt-out also suppresses native Metal page writes");
    }

    // Modern GL rejection never falls back to the legacy short-opcode/semantic path.
    for (bool cache : {false,true}) {
        auto p=fixture();p.pageLocalGL=true;p.semanticEnabled=p.resolverEnabled=true;
        auto before=std::vector<UInt8>(data,data+4096);int calls=UserOpenGL::calls;
        p.patchNativePage(data,0x8000,vnode(driver),cache);
        require(UserOpenGL::calls==calls+(!cache),"only standalone GL reaches the new planner");
        require(!std::memcmp(before.data(),data,4096)&&p.semanticCalls==0&&p.resolverCalls==0,
                "no old GL fallback after the new exclusive owner");
    }
    version={24,6};
    for(bool changed:{false,true})for(bool qa:{false,true}) {
        UserPatches p;p.pageLocalGL=true;p.resolverOnly=qa;
        std::memcpy(data,budgetPage,4096);if(changed)data[0]^=1;
        p.patchNativePage(data,0x5000,vnode(driver),false);
        require((std::memcmp(data+0x6f9,budgetReplace,sizeof(budgetReplace))==0)==(!changed&&!qa),
                "modern GL retains only the exact budget correction and respects QA mode");
    }
    std::puts("production GL guard: NotificationCenter rejected; real exact/context/resolver driver patches pass");
}
'''


def main():
    source = (ROOT / 'NootedRed/UserPatches.cpp').read_text()
    header = (ROOT / 'NootedRed/UserPatches.hpp').read_text()
    signature = method(header, 'struct SignaturePatch\n') + ';'
    shim = SHIM.replace('const int* signatures = nullptr;', signature + '\nconst SignaturePatch* signatures = nullptr;')
    shim = shim.replace('static constexpr size_t kPageSize = 4096;',
                        'static constexpr size_t kPageSize = 4096, kMaxSignatures = 8;')
    shim = shim.replace('void patchSignaturePage(const void*, UInt64, void*) { if (resolverEnabled) resolverCalls++; }',
                        'void patchSignaturePage(const void*, UInt64, void*);')
    arrays = load_arrays(ROOT / 'NootedRed/UserPatches.cpp')
    shim = shim.replace('void patchGLBudgetPage(const void*,UInt64) { ++UserOpenGL::budgetCalls; }',
                        'void patchGLBudgetPage(const void*,UInt64);')
    fixtures = '\n'.join('const UInt8 ' + name + '[] = {' + ','.join(map(str, arrays[key])) + '};'
                         for name, key in [('driverPage', 'kGLDriverDualQuadPage_Sequoia'),
                                           ('resolverContext', 'kResolverDualCtx'),
                                           ('budgetPage','kGLDriverBudgetPage_Sequoia'),
                                           ('budgetFind','kGLDriverBudgetFind'),
                                           ('budgetReplace','kGLDriverBudgetReplace'),
                                           ('vaPitchPage','kVAEncodePitchPage_Sequoia'),
                                           ('vaPitchFind','kVAEncodePitchFind'),
                                           ('vaPitchReplace','kVAEncodePitchReplace')])
    bodies = '\n'.join(method(source, signature) for signature in (
        'auto UserPatches::isTargetVnode(', 'auto UserPatches::isPatchedPage(', 'auto UserPatches::isGLDriverVnode(',
        'void UserPatches::patchSignaturePage(', 'void UserPatches::patchNativePage(',
        '__attribute__((noinline)) void UserPatches::patchGLBudgetPage('))
    with tempfile.TemporaryDirectory(prefix='nred-gl-guard-') as directory:
        cpp = Path(directory) / 'guard.cpp'
        cpp.write_text(shim + '\n#include <vector>\nconst char* const kBootArgGLFixSemanticMTL = "-NRedGLFixSemanticMTL";\n'
                       + fixtures + '\nconst auto& kGLDriverBudgetPage_Sequoia=budgetPage;\nconst auto& kGLDriverBudgetReplace=budgetReplace;\n' + bodies + CASES)
        binary = Path(directory) / 'guard'
        subprocess.run(shlex.split(os.environ.get('CXX', 'c++')) + [
            '-std=c++17', '-Wall', '-Wextra', '-Wno-unused-parameter', str(cpp), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
