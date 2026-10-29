// User-Space Driver Patches
//
// Copyright (C) 2026  ChefKiss.
//
// Licensed under the ChefKiss Open Knowledge License version 1.
//
// This work is licensed to you under the terms of the ChefKiss Open Knowledge
// License, either version 1 of the License, or (at your option) any later
// version published by ChefKiss.
//
// This work may not be used to train or develop artificial intelligence,
// and may not be used with artificial intelligence in any other way. See
// the ChefKiss Open Knowledge License for details.
//
// This work is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// ChefKiss Open Knowledge License for more details.
//
// You should have received a copy of the ChefKiss Open Knowledge License
// along with this work.  If not, see https://git.chefkiss.dev/ChefKiss/OpenKnowledge/raw/branch/master/LICENSE-v1.md.

#include <VDASignaturePlanner.hpp>
#include <VideoPolicy.hpp>
#include <VDATableSelection.hpp>
#include <MediaSafety.hpp>
#include <MediaSafetyPolicy.hpp>
#include <SurfaceSafety.hpp>
#include <SurfaceSafetyPolicy.hpp>
#include <Headers/kern_api.hpp>
#include <Headers/kern_mach.hpp>
#include <Headers/kern_util.hpp>
#include <DeviceProfile.hpp>
#include <GLFixSemanticData.hpp>
#include <NRed.hpp>
#include <PenguinWizardry/KernelVersion.hpp>
#include <UserPatches.hpp>
#include <TahoePatchData.hpp>
#include <UserSubmitGuard.hpp>
#include <UserCodePatch.hpp>
#include <UserPatchMapGate.hpp>
#include <IOKit/IOLocks.h>
#include <kern/thread.h>
#include <UserSharedCacheData.hpp>
#include <UserOpenGL.hpp>
#include <VCNBridge.hpp>
#include <libkern/OSAtomic.h>
#include <libkern/OSTypes.h>
#include <mach/i386/vm_types.h>
#include <sys/vnode.h>
#include <mach/vm_map.h>
#include <mach/vm_region.h>
#include <kern/task.h>
#include <IOKit/IOUserClient.h>
#include <libkern/c++/OSBoolean.h>

static UserPatches moduleInstance;

extern "C" {
    extern char osversion[];
    int proc_pid(proc_t);
    void proc_name(int, char*, int);
    proc_t current_proc(void);
}

namespace
{

    const char* const kBootArgGLFix            = "-NRedGLFix";
    const char* const kBootArgNoGLFix          = "-NRedNoGLFix";
    const char* const kBootArgGLFixOff         = "-NRedGLFixOff";
    const char* const kBootArgGLFixResolveOnly = "-NRedGLFixResolveOnly";
    const char* const kBootArgGLFixResolveOff  = "-NRedGLFixResolveOff";
    const char* const kBootArgGLFixNoResolve   = "-NRedGLFixNoResolve";
    const char* const kBootArgGLFixSemanticMTL = "-NRedGLFixSemanticMTL";
    const char* const kBootArgGLFixSemanticOff = "-NRedGLFixSemanticOff";
    const char* const kBootArgNoSubmitGuard    = "-NRedNoSubmitGuard";
    const char* const kBootArgSubmitGuard      = "-NRedSubmitGuard";
    const char* const kBootArgNoLegacyBlend    = "-NRedNoLegacyBlend";
    const char* const kBootArgLegacyBlend      = "-NRedLegacyBlend";

    struct SharedRegionCheckArgs
    {
        user_addr_t startAddress;
    };
    static_assert(sizeof(SharedRegionCheckArgs) == 8);
    using SharedRegionCheck = int (*)(proc_t, SharedRegionCheckArgs*, int*);

    bool isFairPlayClient(const task_t task)
    {
        if (task == nullptr) { return false; }
        auto* entitlement = IOUserClient::copyClientEntitlement(task, "com.apple.private.fpsd.client");
        const bool client = (entitlement == kOSBooleanTrue);
        if (entitlement != nullptr) { entitlement->release(); }
        return client;
    }

    using GetTaskMap = vm_map_t (*)(task_t);
    using RegionRecurse = kern_return_t (*)(vm_map_t, mach_vm_address_t*, mach_vm_size_t*, natural_t*,
                                            vm_region_recurse_info_t, mach_msg_type_number_t*);
    using CopyIn = int (*)(const void*, void*, size_t);
    using CopyOut = int (*)(const void*, void*, size_t);

    GetTaskMap    getTaskMapFunc{nullptr};
    RegionRecurse queryRegionFunc{nullptr};
    CopyIn        copyInFunc{nullptr};
    CopyOut       copyOutFunc{nullptr};
    IOLock* cachePatchLock{nullptr};
    UserPatchMapGate::Registry<64> cachePatchMaps;

    bool leafProtection(vm_map_t map, const mach_vm_address_t page, vm_prot_t& protection,
                        vm_prot_t* maximum = nullptr)
    {
        if (queryRegionFunc == nullptr) { return false; }
        natural_t depth{0};
        for (UInt32 attempt = 0; attempt < 8; ++attempt) {
            auto address = page;
            mach_vm_size_t size{0};
            vm_region_submap_short_info_data_64_t info{};
            mach_msg_type_number_t count = VM_REGION_SUBMAP_SHORT_INFO_COUNT_64;
            const auto result = queryRegionFunc(map, &address, &size, &depth,
                                                reinterpret_cast<vm_region_recurse_info_t>(&info), &count);
            if (result != KERN_SUCCESS) { return false; }
            if (count < VM_REGION_SUBMAP_SHORT_INFO_COUNT_64 || address > page || page - address >= size
                || size - (page - address) < PAGE_SIZE) { return false; }
            if (!info.is_submap) {
                protection = info.protection;
                if (maximum != nullptr) { *maximum = info.max_protection; }
                return true;
            }
            if (depth == ~0U) { break; }
            ++depth;
        }
        return false;
    }

    struct UserCodeMemory
    {
        vm_map_t map;
        bool read(UInt64 address, void* data, size_t size) const
        { return copyInFunc(reinterpret_cast<const void*>(address), data, size) == 0; }
        bool write(UInt64 address, const void* data, size_t size) const
        { return copyOutFunc(data, reinterpret_cast<void*>(address), size) == 0; }
        bool isRX(UInt64 address) const
        {
            vm_prot_t protection{VM_PROT_NONE};
            return leafProtection(map, address & ~static_cast<UInt64>(PAGE_SIZE - 1), protection)
                   && protection == (VM_PROT_READ | VM_PROT_EXECUTE);
        }
        bool writable(UInt64 address) const
        {
            return vm_protect(map, address & ~static_cast<UInt64>(PAGE_SIZE - 1), PAGE_SIZE,
                              FALSE, VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY) == KERN_SUCCESS;
        }
        bool executable(UInt64 address) const
        {
            return vm_protect(map, address & ~static_cast<UInt64>(PAGE_SIZE - 1), PAGE_SIZE,
                              FALSE, VM_PROT_READ | VM_PROT_EXECUTE) == KERN_SUCCESS;
        }
    };

    __attribute__((noinline)) bool userBytesEqual(UInt64 address, const UInt8* expected, size_t size)
    {
        UInt8 observed[64];
        for (size_t offset = 0; offset < size; offset += sizeof(observed)) {
            const auto remaining = size - offset;
            const auto chunk = remaining < sizeof(observed) ? remaining : sizeof(observed);
            if (copyInFunc(reinterpret_cast<const void*>(address + offset), observed, chunk) != 0
                || memcmp(observed, expected + offset, chunk) != 0) { return false; }
        }
        return true;
    }

    __attribute__((noinline)) bool validSubmitGuardEntry(vm_map_t map, UInt64 method, const UInt8* entry)
    {
        UInt64 target{0};
        memcpy(&target, entry + 6, sizeof(target));
        vm_prot_t protection{VM_PROT_NONE}, maximum{VM_PROT_NONE};
        if (entry[14] != 0x90 || (target & (PAGE_SIZE - 1)) != 0
            || target >= 0x800000000000ULL - PAGE_SIZE
            || !leafProtection(map, target, protection, &maximum)
            || protection != (VM_PROT_READ | VM_PROT_EXECUTE)
            || maximum != (VM_PROT_READ | VM_PROT_EXECUTE)) { return false; }
        UInt8 expected[sizeof(UserSubmitGuardData::Payload)];
        memcpy(expected, UserSubmitGuardData::Payload, sizeof(expected));
        const UInt64 continuation = method + UserSubmitGuardData::MethodPatchSize;
        memcpy(expected + UserSubmitGuardData::PayloadJumpOffset, &continuation, sizeof(continuation));
        return userBytesEqual(target, expected, sizeof(expected));
    }

    // The patch bytes and page images below are specific to one driver build, and the native backend hooks
    // code signing page validation, so this is opt-in until the table has been filled in and tested.
    constexpr bool kGLFixDefaultEnabled = true;

    // Arbitrary non-zero section id for `UserPatcher::BinaryModPatch`; Lilu's ABI treats zero as disabled.
    constexpr UInt32 kLiluPatchSection = 1;

    // Exact patches for
    // `/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver`.
    //
    // TODO: Populate this table from analysis/gl-hwinfo.md, or call `UserPatches::singleton().registerGLDriverFix`
    // with a table in `NRed::init`.  Each entry needs:
    //  - `find`/`replace`/`size`: the bytes to replace (both backends),
    //  - `skip`/`count`: which occurrences to replace; `count` must be non-zero (both backends),
    //  - `segment`: the Mach segment/section holding the patch (Lilu backend only, `SegmentTextText` for `__text`),
    //  - `page`: the exact 4 KiB file page containing the first `find` (native backend only, macOS 11 and newer).
    //
    // A page image can be extracted with, for example:
    //  - `dd if="$kGLDriverPath" of=page.bin bs=4096 skip=$((0xdf000 / 0x1000)) count=1` and then `xxd -i page.bin`.
    //
    // Common GL Driver patch patterns (shared across macOS 14, 15, 26)
    // A1: `_gfx9_HwInfoInitData` hardcodes four shader engines in the Vega10 branch. Renoir has one
    // shader engine, so `rec+0x64 = rec+0x60 * rec+0x78 * rec+0x80` becomes 32 instead of 8 compute
    // units. Site: file offset 0xE081 = page 0xE000 + 0x81.
    static const UInt8 kGLDriverHwInfoFind[]    = {0xC7, 0x47, 0x78, 0x04, 0x00, 0x00, 0x00};
    static const UInt8 kGLDriverHwInfoReplace[] = {0xC7, 0x47, 0x78, 0x01, 0x00, 0x00, 0x00};

    // A2: `_glrAMD_GFX9_UpdateHwCbDualQuadMode` must set `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD` on
    // the iGPU. The original code computes the bit from `rec+0xA0` bit 1, which is set only for the
    // Vega12 branch (0x4F); Renoir takes the Vega10 branch (0x4D), so dual-source blending drops the
    // draw or resets the GPU. Force `or eax, 1` instead of `and eax, ~1`.
    // Site: file offset 0x8160 = page 0x8000 + 0x160; the same 3-byte sequence also occurs at
    // page offset 0x68, hence skip = 1.
    static const UInt8 kGLDriverDualQuadFind[]    = {0x83, 0xE0, 0xFE};
    static const UInt8 kGLDriverDualQuadReplace[] = {0x83, 0xC8, 0x01};

    // Metal counterpart: Gate pattern (jnz -> jmp) for macOS 14 & 15
    static const UInt8 kMTLGateFind[]    = {0x75, 0x0B};
    static const UInt8 kMTLGateReplace[] = {0xEB, 0x0B};



    // Shared by the Tahoe exact-page and resolver tables below.
    static const UInt8 kTahoeMTLGateFind[]    = {0x74, 0x28};
    static const UInt8 kTahoeMTLGateReplace[] = {0xEB, 0x00};
    static const UInt8 kTahoeMTLAllowFind[]   = {0x0F, 0x94, 0xC1};
    static const UInt8 kTahoeMTLAllowReplace[] = {0x31, 0xC9, 0x90};

    #include "UserPatchesVentura.inc"
    #include "UserPatchesSonoma.inc"
    #include "UserPatchesSequoia.inc"
    #include "VDASignatures.inc"
    #include "UserPatchesTahoe.inc"
    #include "UserPatchesGLBudget.inc"
    #include "UserPatchesVAEncode.inc"

    static const UserPatches::PagePatch kVAEncodePitchPatches_Sequoia[] = {
        {UserPatcher::FileSegment::SegmentTextText, kVAEncodePitchPage_Sequoia,
         kVAEncodePitchFind, kVAEncodePitchReplace, sizeof(kVAEncodePitchFind), 0, 1, false, true},
    };

    static const UInt8 kResolverMask32_RipMasked[] = {
        0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,
        0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0x00,0x00,0x00,0x00,0xFF};
    static const UInt8 kResolverMask32[] = {
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
    };

    // macOS 14 (Sonoma) resolver contexts.
    static const UInt8 kResolverHwCtx_Sonoma[] = {
        0xAC, 0x00, 0x00, 0x00, 0x41, 0x83, 0xF8, 0x13, 0x77, 0x45, 0xC7, 0x07, 0x8D, 0x00, 0x00, 0x00,
        0xC7, 0x47, 0x78, 0x04, 0x00, 0x00, 0x00, 0xC5, 0xF8, 0x28, 0x05, 0xF4, 0x19, 0x0E, 0x00, 0xC5,
    };
    static const UInt8 kResolverDualCtx_Sonoma[] = {
        0x88, 0xA0, 0x00, 0x00, 0x00, 0xD1, 0xE9, 0x83, 0xE1, 0x01, 0x8B, 0x83, 0x98, 0x13, 0x00, 0x00,
        0x83, 0xE0, 0xFE, 0x09, 0xC8, 0x89, 0x83, 0x98, 0x13, 0x00, 0x00, 0x48, 0x8B, 0x8B, 0x68, 0x0D,
    };
    static const UInt8 kResolverGateCtx_Sonoma[] = {
        0xFF, 0xFF, 0x48, 0x8B, 0x85, 0x48, 0xFE, 0xFF, 0xFF, 0xF6, 0x80, 0xA0, 0x00, 0x00, 0x00, 0x02,
        0x75, 0x0B, 0x31, 0xC0, 0x48, 0x8B, 0x9D, 0x78, 0xFE, 0xFF, 0xFF, 0xEB, 0x1D, 0x80, 0xBD, 0x80,
    };

    static const UserPatches::SignaturePatch kResolverSignatures_Sonoma[] = {
        {kResolverHwCtx_Sonoma, kResolverMask32, sizeof(kResolverHwCtx_Sonoma), 16, kGLDriverHwInfoReplace,
         sizeof(kGLDriverHwInfoReplace), 0, 1, 0xE000, true},
        {kResolverDualCtx_Sonoma, kResolverMask32, sizeof(kResolverDualCtx_Sonoma), 16, kGLDriverDualQuadReplace,
         sizeof(kGLDriverDualQuadReplace), 0, 1, 0x8000, true},
        {kResolverGateCtx_Sonoma, kResolverMask32, sizeof(kResolverGateCtx_Sonoma), 16, kMTLGateReplace,
         sizeof(kMTLGateReplace), 0, 1, ~static_cast<UInt64>(0)},
    };
    constexpr size_t kResolverSignatureCount_Sonoma = arrsize(kResolverSignatures_Sonoma);

    // macOS 15 (Sequoia) resolver contexts.
    static const UInt8 kResolverHwCtx[] = {
        0xAC, 0x00, 0x00, 0x00, 0x41, 0x83, 0xF8, 0x13, 0x77, 0x45, 0xC7, 0x07, 0x8D, 0x00, 0x00, 0x00,
        0xC7, 0x47, 0x78, 0x04, 0x00, 0x00, 0x00, 0xC5, 0xF8, 0x28, 0x05, 0x50, 0xFE, 0x0D, 0x00, 0xC5,
    };
    static const UInt8 kResolverDualCtx[] = {
        0x88, 0xA0, 0x00, 0x00, 0x00, 0xD1, 0xE9, 0x83, 0xE1, 0x01, 0x8B, 0x83, 0x98, 0x13, 0x00, 0x00,
        0x83, 0xE0, 0xFE, 0x09, 0xC8, 0x89, 0x83, 0x98, 0x13, 0x00, 0x00, 0x48, 0x8B, 0x8B, 0x68, 0x0D,
    };
    static const UInt8 kResolverGateCtx[] = {
        0xFF, 0xFF, 0x48, 0x8B, 0x85, 0x28, 0xFE, 0xFF, 0xFF, 0xF6, 0x80, 0xA0, 0x00, 0x00, 0x00, 0x02,
        0x75, 0x0B, 0x31, 0xC0, 0x4C, 0x8B, 0x9D, 0x80, 0xFE, 0xFF, 0xFF, 0xEB, 0x2C, 0x83, 0xBD, 0x70,
    };

    // Resolver fallback for the 15.8.1 GL/Metal sites.
    static const UserPatches::SignaturePatch kResolverSignatures[] = {
        {kResolverHwCtx, kResolverMask32, sizeof(kResolverHwCtx), 16, kGLDriverHwInfoReplace,
         sizeof(kGLDriverHwInfoReplace), 0, 1, 0xE000, true},
        {kResolverDualCtx, kResolverMask32, sizeof(kResolverDualCtx), 16, kGLDriverDualQuadReplace,
         sizeof(kGLDriverDualQuadReplace), 0, 1, 0x8000, true},
        {kResolverGateCtx, kResolverMask32, sizeof(kResolverGateCtx), 16, kMTLGateReplace,
         sizeof(kMTLGateReplace), 0, 1, ~static_cast<UInt64>(0)},
    };
    constexpr size_t kResolverSignatureCount = arrsize(kResolverSignatures);

    // macOS 26 (Tahoe) resolver contexts.
    // The rip-relative displacement at bytes 27-30 is masked to wildcards for forward-compatibility across minor builds.
    static const UInt8 kResolverMask32_HwTahoe[] = {
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF,
    };

    static const UInt8 kResolverHwCtx_Tahoe[] = {
        0xAC, 0x00, 0x00, 0x00, 0x41, 0x83, 0xF8, 0x13, 0x77, 0x45, 0xC7, 0x07, 0x8D, 0x00, 0x00, 0x00,
        0xC7, 0x47, 0x78, 0x04, 0x00, 0x00, 0x00, 0xC5, 0xF8, 0x28, 0x05, 0x50, 0xF3, 0x0D, 0x00, 0xC5,
    };
    static const UInt8 kResolverDualCtx_Tahoe[] = {
        0x88, 0xA0, 0x00, 0x00, 0x00, 0xD1, 0xE9, 0x83, 0xE1, 0x01, 0x8B, 0x83, 0x98, 0x13, 0x00, 0x00,
        0x83, 0xE0, 0xFE, 0x09, 0xC8, 0x89, 0x83, 0x98, 0x13, 0x00, 0x00, 0x48, 0x8B, 0x8B, 0x68, 0x0D,
    };
    static const UInt8 kResolverGateCtx_Tahoe[] = {
        0xFF, 0xFF, 0xF6, 0x81, 0xA0, 0x00, 0x00, 0x00, 0x02, 0x48, 0x8B, 0x9D, 0x70, 0xFE, 0xFF, 0xFF,
        0x74, 0x28, 0x80, 0xBD, 0x80, 0xFE, 0xFF, 0xFF, 0x00, 0x0F, 0x95, 0xC0, 0x48, 0x8B, 0x8D, 0x78,
    };
    static const UInt8 kResolverAllowCtx_Tahoe[] = {
        0xFF, 0x48, 0xBA, 0x00, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x48, 0x85, 0x54, 0x0B, 0x08,
        0x0F, 0x94, 0xC1, 0x08, 0xC1, 0x0F, 0xB6, 0xC1, 0x41, 0x8B, 0x4C, 0x24, 0x28, 0x83, 0xE1, 0xFE,
    };

    static const UserPatches::SignaturePatch kResolverSignatures_Tahoe[] = {
        {kResolverHwCtx_Tahoe, kResolverMask32_HwTahoe, sizeof(kResolverHwCtx_Tahoe), 16, kGLDriverHwInfoReplace,
         sizeof(kGLDriverHwInfoReplace), 0, 1, 0xE000, true},
        {kResolverDualCtx_Tahoe, kResolverMask32, sizeof(kResolverDualCtx_Tahoe), 16, kGLDriverDualQuadReplace,
         sizeof(kGLDriverDualQuadReplace), 0, 1, 0x8000, true},
        {kResolverGateCtx_Tahoe, kResolverMask32, sizeof(kResolverGateCtx_Tahoe), 16, kTahoeMTLGateReplace,
         sizeof(kTahoeMTLGateReplace), 0, 1, ~static_cast<UInt64>(0)},
        {kResolverAllowCtx_Tahoe, kResolverMask32, sizeof(kResolverAllowCtx_Tahoe), 16, kTahoeMTLAllowReplace,
         sizeof(kTahoeMTLAllowReplace), 0, 1, ~static_cast<UInt64>(0)},
    };
    constexpr size_t kResolverSignatureCount_Tahoe = arrsize(kResolverSignatures_Tahoe);

    // Make the same Metal change in private cache mappings as in the exact/semantic backends.
    // Sonoma/Sequoia retain the stock dualSource || !allowRBPlus predicate after opening its gate.
    bool legacyBlendPlan(UInt32 major, const UInt8* observed, UInt8* target,
                         UInt64& pageOffset, size_t& first, size_t& size)
    {
        const UInt8* reference = nullptr;
        size_t allow = 0;
        if (major == 22) { reference = kMTLControlPage_Ventura; pageOffset = 0x3000BC000ULL; first = 0x22C; }
        else if (major == 23) { reference = kMTLControlPage_Sonoma; pageOffset = 0x30354D000ULL; first = 0x1BC; }
        else if (major == 24) { reference = kMTLControlPage_Sequoia; pageOffset = 0x3087B3000ULL; first = 0x164; }
        else if (major == 25) { reference = kMTLControlPage_Tahoe; pageOffset = 0x310C77000ULL; first = 0x708; }
        else { return false; }

        const UInt8 stockGate[2] = {static_cast<UInt8>(major == 25 ? 0x74 : 0x75),
                                    static_cast<UInt8>(major == 25 ? 0x28 : 0x0B)};
        if (memcmp(reference + first, stockGate, sizeof(stockGate)) != 0) { return false; }
        memcpy(target, observed, PAGE_SIZE);
        const UInt8 gate[2] = {0xEB, static_cast<UInt8>(major == 25 ? 0x00 : 0x0B)};
        if (memcmp(observed + first, reference + first, 2) != 0
            && memcmp(observed + first, gate, 2) != 0) { return false; }
        memcpy(target + first, reference + first, 2);
        size = 2;
        if (major == 25) {
            // Preserve the existing Tahoe gate/allow pair, including the second SETcc occurrence.
            size_t seen = 0;
            for (size_t i = 0; i + sizeof(kTahoeMTLAllowFind) <= PAGE_SIZE; ++i) {
                if (memcmp(reference + i, kTahoeMTLAllowFind, sizeof(kTahoeMTLAllowFind)) == 0
                    && seen++ == 1) { allow = i; break; }
            }
            if (allow < first || allow + sizeof(kTahoeMTLAllowFind) - first > 128) { return false; }
            if (memcmp(observed + allow, kTahoeMTLAllowFind, sizeof(kTahoeMTLAllowFind)) != 0
                && memcmp(observed + allow, kTahoeMTLAllowReplace, sizeof(kTahoeMTLAllowReplace)) != 0) {
                return false;
            }
            memcpy(target + allow, reference + allow, sizeof(kTahoeMTLAllowFind));
            size = allow + sizeof(kTahoeMTLAllowFind) - first;
        }
        // 24H232's complete control-page reference differs from 24H32 only at
        // +0x92C (D0 -> C8). Accept exactly those two full pages, retaining the
        // observed byte in the output. This is not a wildcard or a new write site.
        const bool sequoia24H232 = major == 24 && reference[0x92C] == 0xD0 && target[0x92C] == 0xC8;
        if (sequoia24H232) { target[0x92C] = 0xD0; }
        // No short-opcode-only match: every byte outside our known sites must match the reference.
        if (memcmp(target, reference, PAGE_SIZE) != 0) { return false; }
        if (sequoia24H232) { target[0x92C] = 0xC8; }
        memcpy(target + first, gate, 2);
        if (allow != 0) { memcpy(target + allow, kTahoeMTLAllowReplace, sizeof(kTahoeMTLAllowReplace)); }
        return true;
    }

    // macOS 13 (Ventura) resolver contexts.
    static const UInt8 kResolverHwCtx_Ventura[] = {
        0xAC, 0x00, 0x00, 0x00, 0x41, 0x83, 0xF9, 0x13, 0x77, 0x4D, 0xC7, 0x07, 0x8D, 0x00, 0x00, 0x00,
        0xC7, 0x47, 0x78, 0x04, 0x00, 0x00, 0x00, 0xC5, 0xF8, 0x28, 0x05, 0x06, 0x0B, 0x0F, 0x00, 0xC5,
    };
    static const UInt8 kResolverDualCtx_Ventura[] = {
        0x88, 0xA0, 0x00, 0x00, 0x00, 0xD1, 0xE9, 0x83, 0xE1, 0x01, 0x8B, 0x83, 0x98, 0x13, 0x00, 0x00,
        0x83, 0xE0, 0xFE, 0x09, 0xC8, 0x89, 0x83, 0x98, 0x13, 0x00, 0x00, 0x48, 0x8B, 0x8B, 0x68, 0x0D,
    };
    static const UInt8 kResolverGateCtx_Ventura[] = {
        0xFF, 0xFF, 0x48, 0x8B, 0x85, 0x40, 0xFE, 0xFF, 0xFF, 0xF6, 0x80, 0xA0, 0x00, 0x00, 0x00, 0x02,
        0x75, 0x0B, 0x31, 0xC0, 0x4C, 0x8B, 0xA5, 0x70, 0xFE, 0xFF, 0xFF, 0xEB, 0x24, 0x80, 0xBD, 0x80,
    };
    static const UserPatches::SignaturePatch kResolverSignatures_Ventura[] = {
        {kResolverHwCtx_Ventura, kResolverMask32_RipMasked, sizeof(kResolverHwCtx_Ventura), 16, kGLDriverHwInfoReplace,
         sizeof(kGLDriverHwInfoReplace), 0, 1, 0xE000, true},
        {kResolverDualCtx_Ventura, kResolverMask32, sizeof(kResolverDualCtx_Ventura), 16, kGLDriverDualQuadReplace,
         sizeof(kGLDriverDualQuadReplace), 0, 1, 0x8000, true},
        {kResolverGateCtx_Ventura, kResolverMask32, sizeof(kResolverGateCtx_Ventura), 16, kMTLGateReplace,
         sizeof(kMTLGateReplace), 0, 1, ~static_cast<UInt64>(0)},
    };
    constexpr size_t kResolverSignatureCount_Ventura = arrsize(kResolverSignatures_Ventura);

    static const UserPatches::PagePatch kGLDriverPatches_Ventura[] = {
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverHwInfoPage_Ventura,    kGLDriverHwInfoFind,
         kGLDriverHwInfoReplace,                    sizeof(kGLDriverHwInfoFind),   0, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverDualQuadPage_Ventura,  kGLDriverDualQuadFind,
         kGLDriverDualQuadReplace,                  sizeof(kGLDriverDualQuadFind), 1, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kMTLControlPage_Ventura,        kMTLGateFind,
         kMTLGateReplace,                           sizeof(kMTLGateFind),          0, 1},
    };
    constexpr size_t kGLDriverPatchCount_Ventura = arrsize(kGLDriverPatches_Ventura);

    static const UserPatches::PagePatch kGLDriverPatches_Sonoma[] = {
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverHwInfoPage_Sonoma,    kGLDriverHwInfoFind,
         kGLDriverHwInfoReplace,                    sizeof(kGLDriverHwInfoFind),   0, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverDualQuadPage_Sonoma,  kGLDriverDualQuadFind,
         kGLDriverDualQuadReplace,                  sizeof(kGLDriverDualQuadFind), 1, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kMTLControlPage_Sonoma,        kMTLGateFind,
         kMTLGateReplace,                           sizeof(kMTLGateFind),          0, 1},
    };
    constexpr size_t kGLDriverPatchCount_Sonoma = arrsize(kGLDriverPatches_Sonoma);

    static const UserPatches::PagePatch kGLDriverPatches_Sequoia[] = {
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverBudgetPage_Sequoia, kGLDriverBudgetFind,
         kGLDriverBudgetReplace, sizeof(kGLDriverBudgetFind), 0, 1, true, true},
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverHwInfoPage_Sequoia,    kGLDriverHwInfoFind,
         kGLDriverHwInfoReplace,                    sizeof(kGLDriverHwInfoFind),   0, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverDualQuadPage_Sequoia,  kGLDriverDualQuadFind,
         kGLDriverDualQuadReplace,                  sizeof(kGLDriverDualQuadFind), 1, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kMTLControlPage_Sequoia,        kMTLGateFind,
         kMTLGateReplace,                           sizeof(kMTLGateFind),          0, 1},
    };
    constexpr size_t kGLDriverPatchCount_Sequoia = arrsize(kGLDriverPatches_Sequoia);

    // 26.7.1 uses upstream's gate/allow strategy; the direct-field form remains experimental.

    static const UserPatches::PagePatch kGLDriverPatches_Tahoe[] = {
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverHwInfoPage_Tahoe,    kGLDriverHwInfoFind,
         kGLDriverHwInfoReplace,                    sizeof(kGLDriverHwInfoFind),   0, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kGLDriverDualQuadPage_Tahoe,  kGLDriverDualQuadFind,
         kGLDriverDualQuadReplace,                  sizeof(kGLDriverDualQuadFind), 1, 1, true},
        {UserPatcher::FileSegment::SegmentTextText, kMTLControlPage_Tahoe,        kTahoeMTLGateFind,
         kTahoeMTLGateReplace,                      sizeof(kTahoeMTLGateFind),     0, 1},
        {UserPatcher::FileSegment::SegmentTextText, kMTLControlPage_Tahoe,        kTahoeMTLAllowFind,
         kTahoeMTLAllowReplace,                     sizeof(kTahoeMTLAllowFind),    1, 1},
    };
    constexpr size_t kGLDriverPatchCount_Tahoe = arrsize(kGLDriverPatches_Tahoe);

    // Version/family-aware patch sets.  Add one entry per validated macOS build; the exact page images
    // still gate every site, so a set from another build can never modify a mismatched driver page.
    // `15.8.1` is Darwin 24.6.0 (macOS 15.8.1, build 24H32).
    static const UserPatches::PatchSet kGLDriverPatchSets[] = {
        // Family-specific entries first: all current gfx9 APUs share the same page data, but keeping
        // them separate lets a future family diverge without changing the selection code.
        {"15.x / Renoir-family", PenguinWizardry::KernelVersion(24, 0), PenguinWizardry::KernelVersion(24, 99),
         static_cast<UserPatches::ApuMask>(UserPatches::kApuRenoir | UserPatches::kApuRenoirE |
                                           UserPatches::kApuGreenSardine),
         kGLDriverPatches_Sequoia, kGLDriverPatchCount_Sequoia, kResolverSignatures, kResolverSignatureCount},
        {"15.x / Raven-family", PenguinWizardry::KernelVersion(24, 0), PenguinWizardry::KernelVersion(24, 99),
         static_cast<UserPatches::ApuMask>(UserPatches::kApuRaven | UserPatches::kApuRaven2 |
                                           UserPatches::kApuPicasso),
         kGLDriverPatches_Sequoia, kGLDriverPatchCount_Sequoia, kResolverSignatures, kResolverSignatureCount},
        // Generic fallback for the case where APU attributes are not populated yet.  It is deliberately
        // last so a known family always wins.
        {"15.x / gfx9 APU fallback", PenguinWizardry::KernelVersion(24, 0),
         PenguinWizardry::KernelVersion(24, 99), UserPatches::kApuAll, kGLDriverPatches_Sequoia,
         kGLDriverPatchCount_Sequoia, kResolverSignatures, kResolverSignatureCount},
        // macOS 26.x (Tahoe).
        {"26.x / Tahoe gfx9 APU", PenguinWizardry::KernelVersion(25, 0), PenguinWizardry::KernelVersion(25, 99),
         UserPatches::kApuAll, kGLDriverPatches_Tahoe, kGLDriverPatchCount_Tahoe,
         kResolverSignatures_Tahoe, kResolverSignatureCount_Tahoe},
        // macOS 14.x (Sonoma) fallback.
        {"14.x / Sonoma gfx9 APU", PenguinWizardry::KernelVersion(23, 0), PenguinWizardry::KernelVersion(23, 99),
         UserPatches::kApuAll, kGLDriverPatches_Sonoma, kGLDriverPatchCount_Sonoma,
         kResolverSignatures_Sonoma, kResolverSignatureCount_Sonoma},
        {"13.x / Ventura gfx9 APU", PenguinWizardry::KernelVersion(22, 0), PenguinWizardry::KernelVersion(22, 99),
         UserPatches::kApuAll, kGLDriverPatches_Ventura, kGLDriverPatchCount_Ventura,
         kResolverSignatures_Ventura, kResolverSignatureCount_Ventura},
    };
    constexpr size_t kGLDriverPatchSetCount = sizeof(kGLDriverPatchSets) / sizeof(kGLDriverPatchSets[0]);

}    // namespace

UserPatches& UserPatches::singleton() { return moduleInstance; }

void UserPatches::init()
{
    // `registerGLDriverFix` may already have been called; do not overwrite a custom table then.
    if (this->patches == nullptr && this->patchCount == 0 && this->patchSets == nullptr) {
        this->patchSets     = kGLDriverPatchSets;
        this->patchSetCount = kGLDriverPatchSetCount;
    }

    this->enabled = kGLFixDefaultEnabled;
    if (checkKernelArgument(kBootArgGLFix)) { this->enabled = true; }
    if (checkKernelArgument(kBootArgNoGLFix) || checkKernelArgument(kBootArgGLFixOff)) { this->enabled = false; }

    // The resolver is a GL-only fallback: it must never be active when the GL fix itself is off.
    this->resolverEnabled = this->enabled
                            && !checkKernelArgument(kBootArgGLFixResolveOff)
                            && !checkKernelArgument(kBootArgGLFixNoResolve);
    this->resolverOnly = this->resolverEnabled && checkKernelArgument(kBootArgGLFixResolveOnly);

    // The semantic backend is the generic cross-build fallback: it runs whenever the GL fix is enabled
    // (exact page sets still win), unless explicitly disabled.  Metal context scanning covers the whole
    // shared-cache range; it is forced on here with `-NRedGLFixSemanticMTL`, and enabled automatically
    // later when no exact patch set matches the running build.
    this->semanticPatches    = GLFixSemantic::kPatches;
    this->semanticPatchCount = GLFixSemantic::kPatchCount;
    this->semanticEnabled    = this->enabled && !checkKernelArgument(kBootArgGLFixSemanticOff);
    this->semanticMTLEnabled = this->semanticEnabled && !checkKernelArgument(kBootArgNoLegacyBlend)
                               && checkKernelArgument(kBootArgGLFixSemanticMTL);

    this->vdaEnabled = VideoPolicy::resolve(checkKernelArgument).requested;
    this->vdaResolverEnabled = this->vdaEnabled && checkKernelArgument("-NRedVDAResolve");

    this->submitGuardEnabled = !checkKernelArgument(kBootArgNoSubmitGuard);
    this->legacyBlendEnabled = !checkKernelArgument(kBootArgNoLegacyBlend);
    // Both default on. Explicit enable flags are accepted; explicit disables always win.
    (void)checkKernelArgument(kBootArgSubmitGuard);
    (void)checkKernelArgument(kBootArgLegacyBlend);

    if (!this->enabled && !this->vdaEnabled && !this->submitGuardEnabled && !this->legacyBlendEnabled) {
        DBGLOG("UserPatch", "User-space driver patches are disabled");
        return;
    }

    if (this->enabled) {
        SYSLOG("UserPatch", "Enabling user-space GL driver patches (experimental)");
        if (this->resolverEnabled) {
            SYSLOG("UserPatch", "Resolver fallback enabled%s", this->resolverOnly ? " (resolver-only QA mode)" : "");
        }
        if (this->semanticEnabled) {
            SYSLOG("UserPatch", "Semantic GL fallback enabled (generic across macOS builds)");
        }
        if (this->semanticMTLEnabled) {
            SYSLOG("UserPatch", "Semantic Metal context scanning enabled (forced)");
        }
    }
    if (this->vdaEnabled) { SYSLOG("UserPatch", "Enabling user-space VDA driver patches (experimental)"); }
    if (this->submitGuardEnabled) { SYSLOG("UserPatch", "Enabling user-space Metal SubmitGuard (free tail filler)"); }
}

void UserPatches::registerGLDriverFix(const PagePatch* const patchTable, const size_t count)
{
    this->patches    = patchTable;
    this->patchCount = count;
    this->patchSets  = nullptr;
    this->patchSetCount = 0;
}

void UserPatches::registerPatchSets(const PatchSet* const sets, const size_t count)
{
    this->patchSets     = sets;
    this->patchSetCount = count;
    this->patches       = nullptr;
    this->patchCount    = 0;
}

auto UserPatches::currentApuMask() const -> ApuMask
{
    const auto& attributes = NRed::singleton().getAttributes();

    UInt8 mask = 0;
    if (attributes.isRaven2()) { mask |= kApuRaven2; }
    if (attributes.isPicasso()) { mask |= kApuPicasso; }
    if (attributes.isRenoir()) { mask |= kApuRenoir; }
    if (attributes.isRenoirE()) { mask |= kApuRenoirE; }
    if (attributes.isGreenSardine()) { mask |= kApuGreenSardine; }

    // NRed leaves the attributes empty for the base Raven (0x15DD); model that explicitly.  A zero
    // device ID means NRed has not populated its device information yet, so return an unknown mask and
    // let the selector use the generic fallback rather than guessing a family.
    if (mask == 0) {
        if (NRed::singleton().getDeviceID() == 0x15DD) { mask = kApuRaven; }
        else if (NRed::singleton().getDeviceID() == 0) { return static_cast<ApuMask>(0); }
    }

    return static_cast<ApuMask>(mask);
}

void UserPatches::selectPatchSet()
{
    if (this->patches != nullptr || this->patchCount != 0) { return; }
    if (this->patchSets == nullptr || this->patchSetCount == 0) { return; }

    const auto version = currentKernelVersion();
    const auto apus    = static_cast<UInt8>(this->currentApuMask());

    for (size_t index = 0; index < this->patchSetCount; index++) {
        const auto& set = this->patchSets[index];
        if (version < set.minVersion || version > set.maxVersion) { continue; }

        // An unknown APU (zero mask) may only use the generic fallback, never a family-specific set.
        if (apus == 0) {
            if (set.apus != UserPatches::kApuAll) { continue; }
        }
        else if ((static_cast<UInt8>(set.apus) & apus) == 0) {
            continue;
        }

        this->patches        = set.patches;
        this->patchCount     = set.count;
        this->signatures     = set.signatures;
        this->signatureCount = set.signatureCount;
        for (auto& applied : this->signatureApplied) { applied = 0; }
        // A version range does not prove the exact page will match. Keep both semantic
        // paths available until an exact rendering page has actually been applied.
        if (this->semanticEnabled) { this->semanticMTLEnabled = this->legacyBlendEnabled; }
        SYSLOG("UserPatch", "Selected patch set \"%s\" for macOS %u.%u / APU mask 0x%02X", set.name,
               version.major(), version.minor(), apus);
        return;
    }

    SYSLOG("UserPatch", "No patch set matches macOS %u.%u / APU mask 0x%02X; trying major kernel version fallback",
           version.major(), version.minor(), apus);

    if (getKernelVersion() >= KernelVersion::Tahoe) {
        SYSLOG("UserPatch", "Fallback: selecting macOS 26 (Tahoe) GL/Metal patch set");
        this->patches        = kGLDriverPatches_Tahoe;
        this->patchCount     = kGLDriverPatchCount_Tahoe;
        this->signatures     = kResolverSignatures_Tahoe;
        this->signatureCount = kResolverSignatureCount_Tahoe;
        for (auto& applied : this->signatureApplied) { applied = 0; }
    } else if (getKernelVersion() >= KernelVersion::Sequoia) {
        SYSLOG("UserPatch", "Fallback: selecting macOS 15 (Sequoia) GL/Metal patch set");
        this->patches        = kGLDriverPatches_Sequoia;
        this->patchCount     = kGLDriverPatchCount_Sequoia;
        this->signatures     = kResolverSignatures;
        this->signatureCount = kResolverSignatureCount;
        for (auto& applied : this->signatureApplied) { applied = 0; }
    } else if (getKernelVersion() >= KernelVersion::Sonoma) {
        SYSLOG("UserPatch", "Fallback: selecting macOS 14 (Sonoma) GL/Metal patch set");
        this->patches        = kGLDriverPatches_Sonoma;
        this->patchCount     = kGLDriverPatchCount_Sonoma;
        this->signatures     = kResolverSignatures_Sonoma;
        this->signatureCount = kResolverSignatureCount_Sonoma;
        for (auto& applied : this->signatureApplied) { applied = 0; }
    } else {
        this->patches = kGLDriverPatches_Ventura;
        this->patchCount = kGLDriverPatchCount_Ventura;
        this->signatures = kResolverSignatures_Ventura;
        this->signatureCount = kResolverSignatureCount_Ventura;
        for (auto& applied : this->signatureApplied) { applied = 0; }
    }

    // No version-matched patch set: retain the OS-family exact tables above, then allow the
    // semantic Metal groups to handle a driver whose full page images do not match.
    if (this->semanticEnabled && !this->semanticMTLEnabled) {
        this->semanticMTLEnabled = this->legacyBlendEnabled;
        SYSLOG("UserPatch", "Semantic Metal fallback enabled because no exact patch set matched");
    }
}

void UserPatches::registerVDAFix(const PagePatch* const patchTable, const size_t count, const char* build)
{
    if (patchTable == nullptr || count == 0) { return; }

    if (this->vdaTableCount >= arrsize(this->vdaTables)) {
        SYSLOG("UserPatch", "Too many VDA patch tables, ignoring the extra one");
        return;
    }

    this->vdaTables[this->vdaTableCount++] = {patchTable, count, build};
}

void UserPatches::processPatcher(KernelPatcher& patcher)
{
    NRed::singleton().setProp32("NRedVDAResolverRequested", this->vdaResolverEnabled ? 1 : 0);
    const auto* const profile = DeviceProfile::current();
    const bool vdaAllowed = this->vdaEnabled && profile != nullptr && profile->media.hasVCN0
                            && profile->media.vcnGeneration == DeviceProfile::kVcn2_2
                            && !NRed::singleton().hasExternalVideo();
    this->mediaSafetyEnabled = vdaAllowed && MediaSafetyPolicy::eligible(checkKernelArgument("-NRedVCNSafety"),
        osversion,currentKernelVersion().major(),NRed::singleton().getDeviceID());
    NRed::singleton().setProp32("NRedVCNSafetyOwnsMedia",this->mediaSafetyEnabled?1:0);
    if (this->mediaSafetyEnabled) { this->vdaResolverEnabled=false; }
    this->surfaceSafetyEnabled=this->enabled&&profile&&profile->graphics.conditionalDualQuad
        &&SurfaceSafetyPolicy::canPrepare(checkKernelArgument("-NRedSurfaceFix"),
                                        currentKernelVersion().major(),NRed::singleton().getDeviceID());
    NRed::singleton().setProp32("NRedSurfaceFixRequested",checkKernelArgument("-NRedSurfaceFix")?1:0);
    NRed::singleton().setProp32("NRedSurfaceFixInitialBuildMatched",!strcmp(osversion,"24H232")?1:0);
    NRed::singleton().setProp32("NRedSurfaceFixInitialBuildEmpty",osversion[0]==0?1:0);
    if (this->submitGuardEnabled || this->legacyBlendEnabled || this->mediaSafetyEnabled || this->surfaceSafetyEnabled) {
        this->installSubmitGuard(patcher);
    }

    if (!this->enabled && !this->vdaEnabled) {
        DBGLOG("UserPatch", "User-space driver patches are disabled");
        return;
    }

    auto              glEnabled = this->enabled;
    if (profile != nullptr) {
        SYSLOG("UserPatch", "Device profile: %s (family %s, level %s)", profile->name,
               DeviceProfile::familyName(profile->family), DeviceProfile::levelName(profile->level));
        if (!profile->graphics.conditionalDualQuad) {
            SYSLOG("UserPatch", "Graphics policy disables the conditional dual-quad fix for this profile");
            glEnabled = false;
        }
    }

    // Pick the version/family-aware GL patch set before the native page list is built from it.
    if (glEnabled) { this->selectPatchSet(); }

    // Both fallback mechanisms target GL patch sites; honor the graphics profile gate for both.
    if (!glEnabled) {
        this->resolverEnabled = false;
        this->resolverOnly    = false;
        this->semanticEnabled = false;
        this->semanticMTLEnabled = false;
        this->signatures      = nullptr;
        this->signatureCount  = 0;
    }

    const auto darwin = currentKernelVersion().major();
    this->pageLocalGL = glEnabled && darwin >= 23 && darwin <= 25;
    if (this->pageLocalGL) {
        UserOpenGL::init(darwin, NRed::singleton().getDeviceID(),
                         this->resolverEnabled || this->semanticEnabled, this->resolverOnly);
    }

    // Build the native page list from whichever tables are enabled.  The VDA tables only exist on macOS 11
    // and newer, where the native backend is the one being used.  The profile is the single source of truth
    // for the target: a VCN 2.x device whose profile enables the engine may receive the user-space VA tables
    // (the VCN 2.x profiles, with 0x1638 as the validated target).
    if (this->vdaEnabled && !vdaAllowed) {
        SYSLOG("UserPatch", "VDA patches requested but this profile does not enable the validated VCN 2.x target");
    }

    this->nativePatchCount = 0;
    for (auto& isVDA : this->nativePatchIsVDA) { isVDA = false; }

    if (currentKernelVersion() >= MACOS_11) {
        auto append = [this](const PagePatch* const table, const size_t count, const bool vda)
        {
            for (size_t i = 0; i < count && this->nativePatchCount < kMaxNativePatches; ++i) {
                if (!vda && !table[i].glDriver && !this->legacyBlendEnabled) { continue; }
                if (this->pageLocalGL && !vda && table[i].glDriver && !table[i].exactOnly) { continue; }
                this->nativePatchIsVDA[this->nativePatchCount] = vda;
                this->nativePatches[this->nativePatchCount++]   = table[i];
            }
        };

        if (glEnabled) { append(this->patches, this->patchCount, false); }
        if (vdaAllowed && !this->mediaSafetyEnabled) {
            const bool specific = VDATableSelection::hasSpecific(this->vdaTables, this->vdaTableCount, osversion);
            NRed::singleton().setProp32("NRedVDATableRevision", specific ? 2 : 1);
            for (size_t i = 0; i < this->vdaTableCount; ++i) {
                if (!VDATableSelection::selected(this->vdaTables[i], specific, osversion)) { continue; }
                append(this->vdaTables[i].table, this->vdaTables[i].count, true);
            }
        }

        if (this->nativePatchCount == 0 && !this->pageLocalGL) {
            SYSLOG("UserPatch", "No user-space driver patches are configured, not installing any hooks");
            return;
        }

        SYSLOG_COND(!this->installNativePagePatcher(patcher), "UserPatch",
                    "Failed to install the native page patch backend");
        return;
    }

    if (!glEnabled || this->patches == nullptr || this->patchCount == 0) {
        SYSLOG("UserPatch", "No user-space GL driver patches are configured, not installing any hooks");
        return;
    }

    SYSLOG_COND(!this->installUserPatcher(), "UserPatch", "Failed to register Lilu's user patches");
}

auto UserPatches::installUserPatcher() -> bool
{
    this->liluPatchCount = 0;

    for (size_t patchIndex = 0; patchIndex < this->patchCount; patchIndex++) {
        const auto& patch = this->patches[patchIndex];

        if (patch.find == nullptr || patch.replace == nullptr || patch.size == 0 || patch.count == 0) { continue; }

        if (this->liluPatchCount >= kMaxLiluPatches) {
            SYSLOG("UserPatch", "Too many patches, only the first %zu are used", kMaxLiluPatches);
            break;
        }

        auto& liluPatch   = this->liluPatches[this->liluPatchCount++];
        liluPatch.cpu     = CPU_TYPE_X86_64;
        liluPatch.flags   = 0;
        liluPatch.find    = patch.find;
        liluPatch.replace = patch.replace;
        liluPatch.size    = patch.size;
        liluPatch.skip    = patch.skip;
        liluPatch.count   = patch.count;
        liluPatch.segment = patch.segment;
        liluPatch.section = kLiluPatchSection;
    }

    if (this->liluPatchCount == 0) {
        SYSLOG("UserPatch", "No valid GL driver patches for Lilu's user patcher");
        return false;
    }

    this->liluModInfo.path      = kGLDriverPath;
    this->liluModInfo.patches   = this->liluPatches;
    this->liluModInfo.count     = this->liluPatchCount;
    this->liluModInfo.startTEXT = 0;
    this->liluModInfo.endTEXT   = 0;
    this->liluModInfo.startDATA = 0;
    this->liluModInfo.endDATA   = 0;

    // No process filter is registered: the patch is a page-content patch, and Lilu applies those from the
    // code signing validation hooks for every image that matches, while a process filter would additionally
    // inject the `__RESTRICT` segment into that process (see analysis/lilu-userpatch.md).  Lilu tolerates a
    // zero-sized process list: `onPath` only iterates over `procInfoSize` entries, and `registerPatches` only
    // derives its minimum path length from the list when it is not empty.
    const auto error = lilu.onProcLoad(nullptr, 0, nullptr, nullptr, &this->liluModInfo, 1);
    if (error != LiluAPI::Error::NoError) {
        SYSLOG("UserPatch", "Failed to register user patches with Lilu (%d)", static_cast<int>(error));
        return false;
    }

    DBGLOG("UserPatch", "Registered %zu page patch(es) for %s", this->liluPatchCount, kGLDriverPath);

    return true;
}

auto UserPatches::installNativePagePatcher(KernelPatcher& patcher) -> bool
{
    if (!this->buildNativePatches()) { return false; }

    KernelPatcher::RouteRequest pageRequest{"_cs_validate_page", wrapCsValidatePage, this->orgCsValidatePage};
    if (!patcher.routeMultipleLong(KernelPatcher::KernelID, &pageRequest, 1)) {
        SYSLOG("UserPatch", "Failed to route _cs_validate_page (%d)", static_cast<int>(patcher.getError()));
        patcher.clearError();
        return false;
    }

    // The dyld shared cache and Apple protected pagers validate through the range variant.  The GL driver is
    // not part of the shared cache, so this is only registered when available and never treated as fatal.
    KernelPatcher::RouteRequest rangeRequest{"_cs_validate_range", wrapCsValidateRange, this->orgCsValidateRange};
    UInt32 backends = 1;
    if (!patcher.routeMultipleLong(KernelPatcher::KernelID, &rangeRequest, 1)) {
        DBGLOG("UserPatch", "Failed to route _cs_validate_range, continuing without it (%d)",
               static_cast<int>(patcher.getError()));
        patcher.clearError();
    }
    else { backends |= 2; }
    if (this->pageLocalGL) { NRed::singleton().setProp32("NRedOpenGLBackends", backends); }

    DBGLOG("UserPatch", "Installed the native page patch backend for %zu page(s)", this->nativePageCount);

    return true;
}

auto UserPatches::buildNativePatches() -> bool
{
    this->nativePageCount = 0;

    for (size_t patchIndex = 0; patchIndex < this->nativePatchCount; patchIndex++) {
        const auto& patch = this->nativePatches[patchIndex];

        if (patch.find == nullptr || patch.replace == nullptr || patch.size == 0 || patch.count == 0
            || patch.page == nullptr || patch.size > kMaxPatchSize || patch.skip > kMaxSitesPerPage
            || patch.count > kMaxSitesPerPage)
        {
            SYSLOG("UserPatch", "Patch %zu is invalid; refusing the native page table", patchIndex);
            return false;
        }

        // Locate the complete set of sites before creating a page, so a truncated record can never leave a
        // partially patched driver behind.
        size_t offsets[kMaxSitesPerPage]{};
        size_t matched = 0;
        size_t placed  = 0;
        for (size_t offset = 0; offset + patch.size <= kPageSize; offset++) {
            if (memcmp(patch.page + offset, patch.find, patch.size) != 0) { continue; }

            if (matched++ < patch.skip) { continue; }

            offsets[placed++] = offset;
            if (placed == patch.count) { break; }
        }

        if (placed != patch.count) {
            SYSLOG("UserPatch",
                   "Failed to locate all occurrences of patch %zu (%zu missing); refusing the native page table",
                   patchIndex, patch.count - placed);
            return false;
        }

        NativePage* page{nullptr};
        for (size_t pageIndex = 0; pageIndex < this->nativePageCount; pageIndex++) {
            if (memcmp(this->nativePages[pageIndex].image, patch.page, kPageSize) != 0) { continue; }
            page = &this->nativePages[pageIndex];
            break;
        }

        if (page == nullptr) {
            if (this->nativePageCount >= kMaxNativePages) {
                SYSLOG("UserPatch",
                       "Too many distinct pages for the native backend (%zu); refusing the native page table",
                       kMaxNativePages);
                return false;
            }

            page = &this->nativePages[this->nativePageCount++];
            *page = NativePage{};
            page->image = patch.page;
            page->glDriver = patch.glDriver;
            memcpy(&page->head, patch.page, sizeof(page->head));
        }

        if (page->glDriver != patch.glDriver) {
            SYSLOG("UserPatch", "Conflicting file targets on a native page; refusing the table");
            return false;
        }

        if (page->siteCount + patch.count > kMaxSitesPerPage) {
            SYSLOG("UserPatch",
                   "Too many patch sites on a single page (%zu + %zu > %zu); refusing the native page table",
                   page->siteCount, patch.count, kMaxSitesPerPage);
            return false;
        }

        page->vda = page->vda || this->nativePatchIsVDA[patchIndex];
        page->exactOnly = page->exactOnly || patch.exactOnly;
        for (size_t siteIndex = 0; siteIndex < patch.count; siteIndex++) {
            auto& site   = page->sites[page->siteCount++];
            site.offset  = offsets[siteIndex];
            site.find    = patch.find;
            site.replace = patch.replace;
            site.size    = patch.size;
        }
    }

    if (this->nativePageCount == 0 && !this->pageLocalGL) {
        SYSLOG("UserPatch", "No usable native page patches, each patch needs a 4096 byte page image and a valid site");
        return false;
    }

    if (this->vdaEnabled) {
        // Make a silent no-match after an OS update diagnosable: if the VCN bridge is ready yet
        // NRedVCNUserApplied stays below this count, the system no longer matches the generated data.
        size_t vdaPages = 0;
        for (size_t pageIndex = 0; pageIndex < this->nativePageCount; pageIndex++) {
            vdaPages += this->nativePages[pageIndex].vda ? 1 : 0;
        }
        SYSLOG("UserPatch", "VDA: %zu user-space driver page(s) registered; compare NRedVCNUserApplied to confirm",
               vdaPages);
    }

    return true;
}

auto UserPatches::isPatchedPage(const NativePage& page, const UInt8* const data) const -> bool
{
    if (page.image == nullptr || data == nullptr) { return false; }

    for (size_t offset = 0; offset < kPageSize; offset++) {
        const NativeSite* site{nullptr};
        for (size_t siteIndex = 0; siteIndex < page.siteCount; siteIndex++) {
            const auto& candidate = page.sites[siteIndex];
            if (offset >= candidate.offset && offset < candidate.offset + candidate.size) {
                site = &candidate;
                break;
            }
        }

        if (site != nullptr) {
            if (data[offset] != site->replace[offset - site->offset]) { return false; }
        }
        else if (data[offset] != page.image[offset]) {
            return false;
        }
    }

    return true;
}

void UserPatches::patchVDASignaturePage(const void* data, UInt64 pageOffset, void* vnode, bool cachePage)
{
    if (!this->vdaEnabled || !this->vdaResolverEnabled || cachePage || !data || !vnode
        || !VCNBridge::singleton().loadReady() || isFairPlayClient(current_task())) { return; }
    // Exact standalone image paths only. Shared caches retain verified page tables;
    // no substring matches, application pages or global per-boot suppression.
    char path[PATH_MAX]{};
    int length = sizeof(path);
    if (vn_getpath(reinterpret_cast<vnode_t>(vnode), path, &length) != 0) { return; }
    const bool isVA = strcmp(path, "/System/Library/Extensions/AMDRadeonVADriver2.bundle/Contents/MacOS/AMDRadeonVADriver2") == 0;
    const bool isGVA = strcmp(path, "/System/Library/PrivateFrameworks/AppleGVA.framework/Versions/A/AppleGVA") == 0;
    if (!isVA && !isGVA) { return; }
    const auto major = currentKernelVersion().major();
    if (major < 22 || major > 25) { return; }
    const UserPatches::SignaturePatch* signatures = major == 22 ? kVDAResolverSignatures_Ventura : kVDAResolverSignatures_Modern;
    auto count = major == 22 ? kVDAResolverSignatureCount_Ventura : kVDAResolverSignatureCount_Modern;
    if (isGVA) {
        signatures = major == 22 ? &kGVAResolverSignature_Ventura
                     : major == 23 ? &kGVAResolverSignature_Sonoma
                     : major == 24 ? &kGVAResolverSignature_Sequoia : &kGVAResolverSignature_Tahoe;
        count = 1;
    }
    auto* bytes = static_cast<const UInt8*>(data);
    VDASignaturePlanner::Plan plan{};
    if (!VDASignaturePlanner::build(bytes, signatures, count, pageOffset, plan)) { return; }
    if (MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) { return; }
    // Validate the complete plan again while holding the write lock.
    VDASignaturePlanner::Plan locked{};
    bool changed = VDASignaturePlanner::build(bytes, signatures, count, pageOffset, locked);
    if (changed) {
        for (size_t i = 0; i < locked.count; ++i) {
            const auto& site = locked.sites[i];
            memcpy(const_cast<UInt8*>(bytes) + site.offset, site.replace, site.size);
        }
    }
    const bool restored = MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) == KERN_SUCCESS;
    PANIC_COND(!restored, "UserPatch", "VDA resolver could not restore write protection");
    if (changed) {
        NRed::singleton().setProp32("NRedVDAResolverApplied", 1);
        const auto applied = static_cast<UInt32>(OSIncrementAtomic(&this->vdaAppliedCount) + 1);
        NRed::singleton().setProp32("NRedVCNUserApplied", applied);
    }
}

void UserPatches::patchSignaturePage(const void* const data, const UInt64 pageOffset, void* const vnode)
{
    if (currentKernelVersion().major() == 22 || !this->isTargetVnode(vnode)) { return; }
    if (!this->resolverEnabled || this->signatures == nullptr || this->signatureCount == 0 || data == nullptr) {
        return;
    }

    bool allApplied = true;
    for (size_t i = 0; i < this->signatureCount && i < kMaxSignatures; ++i) {
        if (this->signatureApplied[i] < this->signatures[i].count) {
            allApplied = false;
            break;
        }
    }
    if (allApplied) { return; }

    const auto* const bytes = static_cast<const UInt8*>(data);

    for (size_t signatureIndex = 0; signatureIndex < this->signatureCount; signatureIndex++) {
        const auto& signature = this->signatures[signatureIndex];

        if (signatureIndex < kMaxSignatures && this->signatureApplied[signatureIndex] >= signature.count) {
            continue;
        }

        // A lone Metal opcode/context is insufficient. Exact pages and the paired
        // semantic planner own shared-cache Metal patches.
        if (!signature.glDriver) { continue; }
        if (signature.context == nullptr || signature.mask == nullptr || signature.replace == nullptr) { continue; }
        if (signature.contextSize == 0 || signature.contextSize > kPageSize) { continue; }
        if (signature.patchOffset + signature.replaceSize > signature.contextSize) { continue; }
        if (signature.pageOffset != ~static_cast<UInt64>(0) && signature.pageOffset != pageOffset) { continue; }
        if (signature.glDriver && !this->isGLDriverVnode(vnode)) { continue; }

        auto skip  = signature.skip;
        auto count = signature.count;
        if (signatureIndex < kMaxSignatures && this->signatureApplied[signatureIndex] < count) {
            count -= this->signatureApplied[signatureIndex];
        }

        for (size_t offset = 0; offset + signature.contextSize <= kPageSize; offset++) {
            bool matches = true;
            for (size_t index = 0; index < signature.contextSize; index++) {
                if ((bytes[offset + index] & signature.mask[index])
                    != (signature.context[index] & signature.mask[index]))
                {
                    matches = false;
                    break;
                }
            }
            if (!matches) { continue; }

            if (skip != 0) {
                skip--;
                continue;
            }

            if (MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) {
                SYSLOG("UserPatch", "Resolver: failed to disable kernel write protection");
                return;
            }

            memcpy(const_cast<UInt8*>(bytes) + offset + signature.patchOffset, signature.replace,
                   signature.replaceSize);

            if (MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) {
                SYSLOG("UserPatch", "Resolver: failed to restore kernel write protection");
            }

            SYSLOG("UserPatch", "Resolver patched a signature site at page offset 0x%zX", offset);
            if (signature.glDriver) { NRed::singleton().setProp32("NRedGLFixGLApplied", 1); }
            if (signatureIndex < kMaxSignatures) {
                this->signatureApplied[signatureIndex]++;
            }

            if (--count == 0) { break; }
        }

    }
}

auto UserPatches::isTargetVnode(void* const vnode) const -> bool
{
    if (vnode == nullptr) { return false; }
    const auto* name = vnode_getname(reinterpret_cast<vnode_t>(vnode));
    if (name == nullptr) { return false; }
    const bool target = strcmp(name, "AMDRadeonX5000GLDriver") == 0
        || strcmp(name, "AMDRadeonVADriver") == 0 || strcmp(name, "AMDRadeonVADriver2") == 0
        || strcmp(name, "AppleGVA") == 0 || (strncmp(name, "dyld_shared_cache_x86_64", 24) == 0
            && (name[24] == 0 || name[24] == 'h' || name[24] == '.'));
    vnode_putname(name);
    return target;
}

auto UserPatches::isGLDriverVnode(void* const vnode) const -> bool
{
    if (vnode == nullptr) { return false; }

    const char* const name = vnode_getname(reinterpret_cast<vnode_t>(vnode));
    if (name == nullptr) { return false; }

    const bool found = strcmp(name, "AMDRadeonX5000GLDriver") == 0;

    vnode_putname(name);
    return found;
}

auto UserPatches::patchSemanticPage(const void* const data, void* const vnode, const bool cachePage) -> bool
{
    if (!this->semanticEnabled || data == nullptr || this->semanticPatches == nullptr) { return false; }

    const auto* const bytes = static_cast<const UInt8*>(data);

    auto matchSite = [&](const SemanticPatch& patch, size_t& site) -> bool {
        if (patch.context == nullptr || patch.mask == nullptr || patch.find == nullptr || patch.replace == nullptr) {
            return false;
        }
        if (patch.contextSize == 0 || patch.contextSize > kPageSize || patch.findSize == 0
            || patch.findSize != patch.replaceSize || patch.siteOffset + patch.findSize > patch.contextSize)
        {
            return false;
        }

        int found = -1;
        for (size_t offset = 0; offset + patch.contextSize <= kPageSize; offset++) {
            if ((bytes[offset] & patch.mask[0]) != (patch.context[0] & patch.mask[0])) { continue; }

            bool matches = true;
            for (size_t index = 1; index < patch.contextSize; index++) {
                if ((bytes[offset + index] & patch.mask[index]) != (patch.context[index] & patch.mask[index])) {
                    matches = false;
                    break;
                }
            }
            if (!matches) { continue; }
            if (found >= 0) { return false; }
            found = static_cast<int>(offset);
        }

        if (found < 0) { return false; }

        const auto candidate = static_cast<size_t>(found) + patch.siteOffset;
        if (candidate + patch.findSize > kPageSize) { return false; }
        if (memcmp(bytes + candidate, patch.find, patch.findSize) != 0) { return false; }

        // Instruction-form verification: the masked context is an anchor, the site itself must still be the
        // instruction the semantic kind describes.
        if (patch.kind == kSemanticGLHwInfo) {
            if (patch.siteOffset < 6 || bytes[static_cast<size_t>(found) + patch.siteOffset - 6] != 0xC7) {
                return false;
            }
        } else if (patch.kind == kSemanticGLDualQuad) {
            if (candidate + 5 > kPageSize || bytes[candidate + 3] != 0x09 || bytes[candidate + 4] != 0xC8) {
                return false;
            }
        }

        site = candidate;
        return true;
    };

    auto applySites = [&](const SemanticPatch* const* entries, const size_t* sites, const size_t count) -> bool {
        if (MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) { return false; }

        for (size_t index = 0; index < count; index++) {
            memcpy(const_cast<UInt8*>(bytes) + sites[index], entries[index]->replace, entries[index]->replaceSize);
        }

        if (MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) {
            SYSLOG("UserPatch", "Semantic: failed to restore kernel write protection");
        }
        return true;
    };

    bool patched = false;
    bool glDriver = false;
    bool glChecked = false;
    size_t index = 0;
    while (index < this->semanticPatchCount) {
        const auto& first = this->semanticPatches[index];

        if (first.cachePage) {
            if (!cachePage || !this->semanticMTLEnabled) { index++; continue; }
        } else if (cachePage) {
            index++;
            continue;
        }

        if (first.group == 0) {
            size_t site = 0;
            if (!matchSite(first, site)) { index++; continue; }

            if (!first.cachePage) {
                if (!glChecked) {
                    glDriver  = this->isGLDriverVnode(vnode);
                    glChecked = true;
                }
                if (!glDriver) { index++; continue; }
            }

            const SemanticPatch* entry = &first;
            if (applySites(&entry, &site, 1)) {
                patched = true;
                NRed::singleton().setProp32("NRedGLFixSemantic", 1);
                SYSLOG("UserPatch", "Semantic patch applied: %s at page offset 0x%zX", first.name, site);
            }
            index++;
            continue;
        }

        // A group only applies when every site in it matches the same page.  That is what makes the Metal
        // variants safe on the shared-cache range: a partial or foreign page is left untouched.
        size_t end = index + 1;
        while (end < this->semanticPatchCount && this->semanticPatches[end].group == first.group) { end++; }
        if (end - index > 8) { index = end; continue; }

        const SemanticPatch* entries[8]{};
        size_t               sites[8]{};
        bool                 groupMatched = true;
        for (size_t entryIndex = index; entryIndex < end; entryIndex++) {
            const auto& patch = this->semanticPatches[entryIndex];
            if (!matchSite(patch, sites[entryIndex - index])) {
                groupMatched = false;
                break;
            }
            entries[entryIndex - index] = &patch;
        }

        if (groupMatched && applySites(entries, sites, end - index)) {
            NRed::singleton().setProp32("NRedGLFixSemanticMetal", 1);
            SYSLOG("UserPatch", "Semantic Metal group %u applied (%zu site(s))", first.group, end - index);
            // Exactly one Metal variant applies per page; the Tahoe direct form is ordered before the
            // gate/allow pair so a 26.x page takes the direct-field patch only.
            return true;
        }

        index = end;
    }

    return patched;
}

__attribute__((noinline)) void UserPatches::patchGLBudgetPage(const void* const data, const UInt64 pageOffset)
{
    // Independent 512 MiB resource-list correction: keep its exact page and QA gates.
    if (currentKernelVersion().major() != 24 || this->resolverOnly || pageOffset != 0x5000
        || memcmp(data, kGLDriverBudgetPage_Sequoia, kPageSize) != 0) { return; }
    constexpr size_t site = 0x6F9;
    if (MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) { return; }
    const bool fresh = memcmp(data, kGLDriverBudgetPage_Sequoia, kPageSize) == 0;
    if (fresh) {
        memcpy(const_cast<UInt8*>(static_cast<const UInt8*>(data)) + site,
               kGLDriverBudgetReplace, sizeof(kGLDriverBudgetReplace));
    }
    bool restored = MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) == KERN_SUCCESS;
    if (!restored && MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) == KERN_SUCCESS) {
        restored = MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) == KERN_SUCCESS;
    }
    UserOpenGL::reportBudgetResult(fresh, restored);
}

__attribute__((noinline)) void UserPatches::patchNativePage(const void* const data, const UInt64 pageOffset, void* const vnode,
                                  const bool cachePage)
{
    if (data == nullptr || !this->isTargetVnode(vnode)) { return; }
    if (this->pageLocalGL && this->isGLDriverVnode(vnode)) {
        // No legacy exact/context/semantic fallback after a new planner rejection.
        // A cache pager must never masquerade as the standalone GL executable.
        if (!cachePage) {
            UserOpenGL::patchPage(data, pageOffset);
            this->patchGLBudgetPage(data, pageOffset);
        }
        return;
    }

    for (size_t pageIndex = 0; pageIndex < this->nativePageCount; pageIndex++) {
        const auto& page = this->nativePages[pageIndex];
        if (!page.vda && !page.glDriver && !this->legacyBlendEnabled) { continue; }
        // GL resolver QA must not suppress exact VA/AppleGVA patches.
        if (this->resolverOnly && !page.vda) { continue; }

        // Cheap first-word fingerprint before the full 4 KiB compare: the validation hook runs for every
        // code-signed page, so avoid 12 full-page memcmps for every page.
        UInt64 head{0};
        memcpy(&head, data, sizeof(head));
        if (head != page.head || memcmp(page.image, data, kPageSize) != 0) { continue; }
        if (page.glDriver && !this->isGLDriverVnode(vnode)) { continue; }

        // VDA patches are only applied when the VCN bridge actually prepared both drivers and loaded X6000.
        // If it failed (ABI mismatch, X6000 load failure), the stock VA/GVA driver stays in place and decode
        // falls back to software instead of trying to use a non-existing engine.
        if (page.vda && !VCNBridge::singleton().loadReady()) {
            DBGLOG("UserPatch", "VDA page matched but the VCN bridge is not ready; leaving it unpatched");
            continue;
        }

        if (page.vda && isFairPlayClient(current_task())) {
            DBGLOG("UserPatch", "Skipping VDA patches for FairPlay client task");
            continue;
        }

        // The page matches, so these checks can only fail when the table is inconsistent; never patch then.
        for (size_t siteIndex = 0; siteIndex < page.siteCount; siteIndex++) {
            const auto& site = page.sites[siteIndex];
            if (memcmp(static_cast<const UInt8*>(data) + site.offset, site.find, site.size) != 0) {
                SYSLOG("UserPatch", "Page matched but a patch site did not, skipping the page");
                return;
            }
        }

        if (MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) {
            SYSLOG("UserPatch", "Failed to disable kernel write protection");
            return;
        }

        for (size_t siteIndex = 0; siteIndex < page.siteCount; siteIndex++) {
            const auto& site = page.sites[siteIndex];
            memcpy(const_cast<UInt8*>(static_cast<const UInt8*>(data)) + site.offset, site.replace, site.size);
        }

        if (MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) {
            SYSLOG("UserPatch", "Failed to restore kernel write protection");
        }

        DBGLOG("UserPatch", "Patched %zu site(s) in a user-space driver page", page.siteCount);
        if (page.glDriver) {
            NRed::singleton().setProp32("NRedGLFixGLApplied", 1);
            SYSLOG("UserPatch", "GL driver exact page patched at file offset 0x%llX", pageOffset);
        }

        if (!page.vda && !checkKernelArgument(kBootArgGLFixSemanticMTL)) {
            this->semanticEnabled = false;
            this->semanticMTLEnabled = false;
        }

        if (page.vda) {
            const auto applied = static_cast<UInt32>(OSIncrementAtomic(&this->vdaAppliedCount) + 1);
            NRed::singleton().setProp32("NRedVCNUserApplied", applied);
        }

        return;
    }

    // The page may already contain our replacement bytes from an earlier validation (the page cache is
    // shared).  Do not rescan it with the resolver; that would only produce false "signature not found"
    // errors and unnecessary work.
    // A page that matches every individual patch site but not the whole stored image means the table was
    // built from a different (or polluted) build of the driver: the patch is silently skipped and the
    // failure only surfaces indirectly (e.g. VideoToolbox falling back to software).  Log it once per
    // declared page.  All sites must match, otherwise an unrelated page with colliding bytes at one site
    // would trip the one-shot flag and suppress the diagnostic for the real target page.
    // The memcmp stays in bounds by construction: buildNativePatches() rejects null find/zero or oversized
    // sites and only registers offsets found by scanning with `offset + size <= kPageSize`, and `data`
    // always addresses a full page here.
    for (size_t pageIndex = 0; pageIndex < this->nativePageCount; pageIndex++) {
        if (this->isPatchedPage(this->nativePages[pageIndex], static_cast<const UInt8*>(data))) { return; }
    }

    // The VDA resolver is a separate, explicit QA path. It never scans the
    // shared cache or runs under the GL resolver's policy.
    if (this->vdaResolverEnabled) { this->patchVDASignaturePage(data, pageOffset, vnode, cachePage); }

    // No site-only fallback. Unknown pages remain stock; modern GL has its own
    // whole-function/page-local planner and Metal uses verified paired semantics.
    if (currentKernelVersion().major() == 22) { return; }

    if (this->resolverOnly) {
        this->patchSignaturePage(data, pageOffset, vnode);
        return;
    }

    // Generic fallback: locate the sites by instruction context instead of a build-specific page image.
    // This is what makes the GL fix work on macOS builds that have no page table entry.
    if (this->patchSemanticPage(data, vnode, cachePage)) { return; }

    this->patchSignaturePage(data, pageOffset, vnode);
}

__attribute__((noinline)) void UserPatches::wrapCsValidatePage(void* const vnode, void* const pager, const UInt64 pageOffset,
                                     const void* const data, int* const validated, int* const tainted, int* const nx)
{
    FunctionCast(wrapCsValidatePage, singleton().orgCsValidatePage)(vnode, pager, pageOffset, data, validated, tainted,
                                                                    nx);

    // Preserve native outputs; accept boolean success or the x86 whole-page bitmap.
    if (validated && (*validated == 1 || *validated == 0xF) && tainted && *tainted == 0
        && nx && *nx == 0 && (pageOffset & (kPageSize - 1)) == 0) {
        singleton().patchNativePage(data, pageOffset, vnode, false);
    }
}

__attribute__((noinline)) boolean_t UserPatches::wrapCsValidateRange(void* const vnode, void* const pager, const UInt64 pageOffset,
                                           const void* const data, const UInt64 dataSize, unsigned* const tainted)
{
    const auto result = FunctionCast(wrapCsValidateRange, singleton().orgCsValidateRange)(vnode, pager, pageOffset,
                                                                                          data, dataSize, tainted);

    if (result == 0 || !tainted || *tainted != 0 || data == nullptr
        || (pageOffset & (kPageSize - 1)) != 0 || dataSize > ~static_cast<UInt64>(0) - pageOffset) { return result; }

    const auto* const bytes = static_cast<const UInt8*>(data);
    const bool cachePage = !singleton().isGLDriverVnode(vnode);
    if (!cachePage && (pageOffset > UserOpenGL::MaxFileSize
        || dataSize > UserOpenGL::MaxFileSize - pageOffset)) { return result; }
    for (size_t offset = 0; offset + kPageSize <= dataSize; offset += kPageSize) {
        singleton().patchNativePage(bytes + offset, pageOffset + offset, vnode, cachePage);
    }

    return result;
}

// Keep patching frames out of the chained native syscall, including optimized builds.
__attribute__((noinline)) int UserPatches::wrapSharedRegionCheck(proc_t process, void* args, int* returnValue)
{
    auto& patches = singleton();
    const auto result = FunctionCast(wrapSharedRegionCheck, patches.orgSharedRegionCheck)(process, args, returnValue);
    if (result == 0 && (patches.submitGuardEnabled || patches.legacyBlendEnabled || patches.mediaSafetyEnabled || patches.surfaceSafetyEnabled) && args != nullptr) {
        const auto map = getTaskMapFunc ? getTaskMapFunc(current_task()) : nullptr;
        UserPatchMapGate::Lease<64> lease(cachePatchMaps, cachePatchLock, map, current_thread());
        if (lease) {
            patches.applySubmitGuard(process, args);
        } else {
            NRed::singleton().setProp32("NRedUserMapGateRejected", 1);
        }
    }
    return result;
}

__attribute__((noinline)) void UserPatches::applySubmitGuard(proc_t process, void* rawArgs)
{
    if (getTaskMapFunc == nullptr || copyInFunc == nullptr || copyOutFunc == nullptr) {
        return;
    }

    const auto kernelMajor = currentKernelVersion().major();
    const auto methodOffset = UserSubmitGuardData::getMethodOffset(kernelMajor);
    if (methodOffset == 0 && !this->legacyBlendEnabled && !this->mediaSafetyEnabled && !this->surfaceSafetyEnabled) { return; }

    auto map = getTaskMapFunc(current_task());
    if (map == nullptr) {
        return;
    }

    mach_vm_offset_t base = UserSubmitGuardData::kDyldSharedCacheBase;
    if (rawArgs != nullptr) {
        const auto* args = static_cast<const SharedRegionCheckArgs*>(rawArgs);
        if (args->startAddress != 0) {
            mach_vm_offset_t userBase{0};
            if (copyInFunc(reinterpret_cast<const void*>(args->startAddress), &userBase, sizeof(userBase)) == 0 && userBase != 0) {
                base = userBase;
            }
        }
    }

    UInt8 cacheHeader[104]{};
    if (base >= 0x800000000000ULL - methodOffset
        || copyInFunc(reinterpret_cast<const void*>(base), cacheHeader, sizeof(cacheHeader)) != 0
        || !UserSharedCacheData::matches(kernelMajor, cacheHeader)) {
        NRed::singleton().setProp32("NRedSubmitGuardRejected", 1);
        return;
    }
    const bool submitReady=!this->submitGuardEnabled
        ||(methodOffset!=0&&this->installMetalSubmitGuard(map,base+methodOffset,process));
    auto surface=SurfaceSafety::Result::Rejected;
    if(SurfaceSafetyPolicy::eligible(this->surfaceSafetyEnabled,osversion,kernelMajor,
                                     NRed::singleton().getDeviceID())&&submitReady&&!isFairPlayClient(current_task())) {
        NRed::singleton().setProp32("NRedSurfaceFixRuntimeBuildMatched",1);
        surface=SurfaceSafety::install(map,base,NRed::singleton().getDeviceID(),this->legacyBlendEnabled,process?proc_pid(process):0);
        if(surface==SurfaceSafety::Result::Halted)return;
    }
    if (this->mediaSafetyEnabled && VCNBridge::singleton().loadReady() && !isFairPlayClient(current_task())) {
        MediaSafety::install(map,base,process?proc_pid(process):0);
    }
    // Independent of SubmitGuard installation success and repeated shared-region checks.
    if (this->legacyBlendEnabled && surface!=SurfaceSafety::Result::Installed) { this->applyLegacyBlend(map, base, process); }

}

__attribute__((noinline)) bool UserPatches::installMetalSubmitGuard(vm_map_t map,UInt64 method,proc_t process)
{
    UInt8 entry[UserSubmitGuardData::MethodPatchSize];
    if (copyInFunc(reinterpret_cast<const void*>(method), entry, sizeof(entry)) != 0) {
        return false;
    }

    static constexpr UInt8 patchedPrefix[6] = {0xFF, 0x25, 0x00, 0x00, 0x00, 0x00};
    if (memcmp(entry, patchedPrefix, sizeof(patchedPrefix)) == 0) {
        const bool valid=validSubmitGuardEntry(map,method,entry);
        if (!valid) { NRed::singleton().setProp32("NRedSubmitGuardRejected", 2); }
        return valid;
    }

    if (memcmp(entry, UserSubmitGuardData::MethodOriginal, sizeof(entry)) != 0) {
        // Entry does not match expected prologue; safely avoid touching.
        return false;
    }

    vm_address_t page{0};
    auto result = vm_allocate(map, &page, PAGE_SIZE, VM_FLAGS_ANYWHERE);
    if (result != KERN_SUCCESS) {
        return false;
    }

    UInt8 payload[sizeof(UserSubmitGuardData::Payload)];
    memcpy(payload, UserSubmitGuardData::Payload, sizeof(payload));
    const UInt64 continuation = method + UserSubmitGuardData::MethodPatchSize;
    memcpy(payload + UserSubmitGuardData::PayloadJumpOffset, &continuation, sizeof(continuation));

    if (copyOutFunc(payload, reinterpret_cast<void*>(page), sizeof(payload)) != 0) {
        vm_deallocate(map, page, PAGE_SIZE);
        return false;
    }

    if (!userBytesEqual(page, payload, sizeof(payload))) {
        vm_deallocate(map, page, PAGE_SIZE);
        return false;
    }
    result = vm_protect(map, page, PAGE_SIZE, FALSE, VM_PROT_READ | VM_PROT_EXECUTE);
    // Seal only our new allocation. Existing cache pages retain their maximum rights
    // so the verified entry rollback can still acquire a private writable copy.
    if (result != KERN_SUCCESS
        || vm_protect(map, page, PAGE_SIZE, TRUE, VM_PROT_READ | VM_PROT_EXECUTE) != KERN_SUCCESS) {
        vm_deallocate(map, page, PAGE_SIZE);
        return false;
    }

    UInt8 patch[UserSubmitGuardData::MethodPatchSize];
    memset(patch, 0x90, sizeof(patch));
    memcpy(patch, patchedPrefix, sizeof(patchedPrefix));
    const UInt64 target = page;
    memcpy(patch + 6, &target, sizeof(target));

    UserCodeMemory memory{map};
    vm_prot_t protection{VM_PROT_NONE}, maximum{VM_PROT_NONE};
    if (!leafProtection(map, page, protection, &maximum)
        || protection != (VM_PROT_READ | VM_PROT_EXECUTE)
        || maximum != (VM_PROT_READ | VM_PROT_EXECUTE)) {
        vm_deallocate(map, page, PAGE_SIZE);
        return false;
    }
    const auto installed = UserCodePatch::write(memory, method, entry, patch, sizeof(patch));
    if (!installed.applied) {
        // A partially written entry might still reference this payload. Never leave it dangling.
        if (installed.originalRestored) { vm_deallocate(map, page, PAGE_SIZE); }
        NRed::singleton().setProp32("NRedSubmitGuardRejected", installed.originalRestored ? 3 : 4);
        return false;
    }
    {
        static volatile UInt32 appliedCounter{0};
        const auto count = static_cast<UInt32>(OSIncrementAtomic(&appliedCounter) + 1);
        NRed::singleton().setProp32("NRedSubmitGuardApplied", count);

        const auto proc = (process != nullptr) ? process : current_proc();
        if (proc != nullptr) {
            const auto pid = proc_pid(proc);
            char name[32]{};
            if (pid > 0) { proc_name(pid, name, sizeof(name)); }
            name[sizeof(name) - 1] = '\0';
            if (strcmp(name, "WindowServer") == 0) {
                NRed::singleton().setProp32("NRedSubmitGuardWindowServerPID", static_cast<UInt32>(pid));
                NRed::singleton().setProp32("NRedSubmitGuardWindowServerApplied", 1);
            }
            DBGLOG("UserPatch", "SubmitGuard installed in %s (PID %d)", name, pid);
        }
    }
    return true;
}

__attribute__((noinline)) void UserPatches::applyLegacyBlend(vm_map_t map, mach_vm_offset_t base, proc_t process)
{
    const auto kernelMajor = currentKernelVersion().major();
    const UInt64 offset = kernelMajor == 22 ? 0x3000BC000ULL : kernelMajor == 23 ? 0x30354D000ULL : kernelMajor == 24 ? 0x3087B3000ULL
                          : kernelMajor == 25 ? 0x310C77000ULL : 0;
    if (offset == 0 || base >= 0x800000000000ULL - offset - PAGE_SIZE) { return; }
    auto* pages = Buffer::create<UInt8>(2 * PAGE_SIZE);
    if (pages == nullptr) { return; }
    auto* observed = pages;
    auto* target = pages + PAGE_SIZE;
    UInt64 pageOffset{0};
    size_t first{0}, size{0};
    UserCodeMemory memory{map};
    const auto address = base + offset;
    if (!memory.isRX(address) || !memory.read(address, observed, PAGE_SIZE)
        || !legacyBlendPlan(kernelMajor, observed, target, pageOffset, first, size) || pageOffset != offset) {
        Buffer::deleter(pages);
        NRed::singleton().setProp32("NRedLegacyBlendRejected", 1);
        return;
    }
    const bool already = memcmp(observed, target, PAGE_SIZE) == 0;
    const auto written = already ? UserCodePatch::Result{true, false}
                                 : UserCodePatch::write(memory, address + first, observed + first,
                                                       target + first, size);
    Buffer::deleter(pages);
    if (!written.applied) {
        NRed::singleton().setProp32("NRedLegacyBlendRejected", written.originalRestored ? 2 : 3);
        return;
    }
    // Counts observations as well as writes; repeated shared-region checks remain idempotent.
    {
        static volatile UInt32 blendCounter{0};
        const auto count = static_cast<UInt32>(OSIncrementAtomic(&blendCounter) + 1);
        NRed::singleton().setProp32("NRedLegacyBlendApplied", count);

        const auto proc = (process != nullptr) ? process : current_proc();
        if (proc != nullptr) {
            const auto pid = proc_pid(proc);
            char name[32]{};
            if (pid > 0) { proc_name(pid, name, sizeof(name)); }
            name[sizeof(name) - 1] = '\0';
            if (strcmp(name, "WindowServer") == 0) {
                NRed::singleton().setProp32("NRedLegacyBlendWindowServerPID", static_cast<UInt32>(pid));
                NRed::singleton().setProp32("NRedLegacyBlendWindowServerApplied", 1);
            }
            DBGLOG("UserPatch", "LegacyBlend patched in %s (PID %d)", name, pid);
        }
    }
}

bool UserPatches::installSubmitGuard(KernelPatcher& patcher)
{
    const auto kernelMajor = currentKernelVersion().major();
    if (kernelMajor != 22 && kernelMajor != 23 && kernelMajor != 24 && kernelMajor != 25) {
        DBGLOG("UserPatch", "SubmitGuard not supported on Darwin %u", kernelMajor);
        return false;
    }

    getTaskMapFunc = reinterpret_cast<GetTaskMap>(patcher.solveSymbol(KernelPatcher::KernelID, "_get_task_map"));
    patcher.clearError();
    queryRegionFunc = reinterpret_cast<RegionRecurse>(
        patcher.solveSymbol(KernelPatcher::KernelID, "_mach_vm_region_recurse"));
    patcher.clearError();
    copyInFunc = reinterpret_cast<CopyIn>(patcher.solveSymbol(KernelPatcher::KernelID, "_copyin"));
    patcher.clearError();
    copyOutFunc = reinterpret_cast<CopyOut>(patcher.solveSymbol(KernelPatcher::KernelID, "_copyout"));
    patcher.clearError();

    if (!getTaskMapFunc || !queryRegionFunc || !copyInFunc || !copyOutFunc) {
        SYSLOG("UserPatch", "Failed to resolve kernel symbols for SubmitGuard");
        return false;
    }

    if (this->mediaSafetyEnabled && !MediaSafety::configure(copyInFunc,copyOutFunc,queryRegionFunc)) {
        SYSLOG("UserPatch","Private video safety adapter unavailable; media remains stock");
    }
    if(this->surfaceSafetyEnabled&&!SurfaceSafety::configure(copyInFunc,copyOutFunc,queryRegionFunc)) {
        this->surfaceSafetyEnabled=false;
        SYSLOG("UserPatch","Private surface adapter unavailable; existing rendering path retained");
    }
    // Allocate once, before publishing the hook. Keep this lock alive for the boot,
    // including a routing failure: no request can observe a freed gate.
    if (cachePatchLock == nullptr) { cachePatchLock = IOLockAlloc(); }
    if (cachePatchLock == nullptr) {
        SYSLOG("UserPatch", "Cannot allocate shared-cache transaction gate");
        return false;
    }
    KernelPatcher::RouteRequest request{"_shared_region_check_np", wrapSharedRegionCheck, this->orgSharedRegionCheck};
    if (!patcher.routeMultipleLong(KernelPatcher::KernelID, &request, 1)) {
        patcher.clearError();
        SYSLOG("UserPatch", "Failed to route _shared_region_check_np for SubmitGuard");
        return false;
    }

    NRed::singleton().setProp32("NRedUserMapGateRevision", 1);
    NRed::singleton().setProp32("NRedSurfaceFixEnabled",this->surfaceSafetyEnabled?1:0);
    NRed::singleton().setProp32("NRedSubmitGuardSupported", UserSubmitGuardData::getMethodOffset(kernelMajor) != 0 ? 1 : 0);
    NRed::singleton().setProp32("NRedSubmitGuardEnabled", this->submitGuardEnabled && UserSubmitGuardData::getMethodOffset(kernelMajor) != 0 ? 1 : 0);
    NRed::singleton().setProp32("NRedSubmitGuardVersion", 2);
    NRed::singleton().setProp32("NRedLegacyBlendEnabled", this->legacyBlendEnabled ? 1 : 0);
    NRed::singleton().setProp32("NRedLegacyBlendVersion", 2);
    SYSLOG("UserPatch", "Shared-cache controls for Darwin %u (verified submit offset 0x%llX)", kernelMajor,
           UserSubmitGuardData::getMethodOffset(kernelMajor));
    return true;
}
