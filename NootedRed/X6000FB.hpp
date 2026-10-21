// AMDRadeonX6000Framebuffer Patches
//
// Copyright (C) 2022-2026  ChefKiss.
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

#pragma once
#include <AGDC/VendorInfo.hpp>
#include <GPUDriversAMD/FB/AmdAsicInfo.hpp>
#include <GPUDriversAMD/FB/AmdDeviceMemoryManager.hpp>
#include <GPUDriversAMD/FB/BiosParser.hpp>
#include <Headers/kern_patcher.hpp>

class X6000FB
{
    using IRQMGRWriteRegister_t = void(void* ctx, UInt64 off, UInt32 value);
    using IRQMGRReadRegister_t  = UInt32(void* ctx, UInt64 off);
    using mapMemorySubRange_t   = IOReturn(void* self, AmdReservedMemorySelector selector, size_t atOffset,
                                           size_t withSize, IOOptionBits andAttributes);
    using messageAccelerator_t  = IOReturn(void* self, UInt32 requestType, void* arg2, void* arg3, void* arg4);
    using readBiosImage_t       = size_t(const void* self, UInt8* buffer, size_t bufferSize);
    using validateBiosImage_t   = bool(const void* self, UInt8* buffer, size_t bufferSize);

    static constexpr UInt32 IOFBRequestControllerEnabled = 0x1B;

    mach_vm_address_t      orgIH40IVRingInitHardware{0};
    IRQMGRWriteRegister_t* orgIRQMGRWriteRegister{nullptr};
    IRQMGRReadRegister_t*  irqMGRReadRegister{nullptr};
    mach_vm_address_t      orgCreateRegisterAccess{0};
    mapMemorySubRange_t*   mapMemorySubRange{nullptr};
    mach_vm_address_t      orgDpReceiverPowerCtrl{0};
    mach_vm_address_t      orgDpEnableLinkPhy{0};
    mach_vm_address_t      orgAtomExecute{0};
    mach_vm_address_t      orgAtomJump{0};
    mach_vm_address_t      orgAtomJumpBelowEqual{0};
    mach_vm_address_t      orgAtomJumpNotEqual{0};
    mach_vm_address_t      orgReadValidateReg32{0};
    using readDpcd_t = int(void* link, UInt32 address, UInt8* data, UInt32 count);
    using writeDpcd_t = int(void* link, UInt32 address, const UInt8* data, UInt32 count);
    readDpcd_t* readDpcd{nullptr};
    writeDpcd_t* writeDpcd{nullptr};
    messageAccelerator_t*  orgMessageAccelerator{nullptr};
    mach_vm_address_t      orgControllerPowerUp{0};
    mach_vm_address_t      orgCreateObjectInfo{0};
    mach_vm_address_t      orgCreateVramInfo{0};
    mach_vm_address_t      orgGetVendorInfo{0};
    readBiosImage_t*       readEfiAtomBiosImage{nullptr};
    readBiosImage_t*       readPciAtomBiosImage{nullptr};
    validateBiosImage_t*   validateAtomBiosImage{nullptr};
    mach_vm_address_t      orgCreatePspDirectory{0};

public:
    static X6000FB& singleton();

    void processKext(KernelPatcher& patcher, size_t id, mach_vm_address_t slide, size_t size);

private:
    static UInt16                           getEnumeratedRevision();
    static IOReturn                         wrapPopulateVramInfo(AmdAtomVramInfo* self, AtomFirmwareInfo& fwInfo);
    static bool                             wrapIH40IVRingInitHardware(void* ctx, void* ring);
    static void                             wrapIRQMGRWriteRegister(void* ctx, UInt64 index, UInt32 value);
    static void*                            wrapCreateRegisterAccess(void* initData);
    static IOReturn                         initialiseReservedVRAM(void* self);
    static const AmdAsicBrandingTableEntry* getGpuBrandingNameListRaven(const void* self);
    static const AmdAsicBrandingTableEntry* getGpuBrandingNameListPicasso(const void* self);
    static const AmdAsicBrandingTableEntry* getGpuBrandingNameListRenoir(const void* self);
    static IOReturn                         dummyIOReturnSuccess();
    static IOReturn                         getTriageHardwareDataRV(void* self, UInt32 fbIndex, void* triageData);
    static IOReturn                         getTriageHardwareDataRN(void* self, UInt32 fbIndex, void* triageData);
    static void                             wrapDpReceiverPowerCtrl(void* link, bool powerOn);
    void installDpRecovery(KernelPatcher& patcher, size_t id, mach_vm_address_t slide, size_t size);
    static void wrapDpEnableLinkPhy(void* link, UInt32 signal, UInt32 clockSource, const void* settings);
    static bool wrapAtomExecute(void* self, UInt32 table, void* parameters, UInt32 options);
    static bool checkAtomBranch(void* context);
    static void wrapAtomJump(void* context);
    static void wrapAtomJumpBelowEqual(void* context);
    static void wrapAtomJumpNotEqual(void* context);
    static UInt32 wrapReadValidateReg32(void* self, UInt32 index);
    static UInt32                           wrapControllerPowerUp(void* self);
    static void*                            wrapCreateObjectInfo(void* helper, UInt32 tableOffset);
    static AmdAtomVramInfo*                 wrapCreateVramInfo(AmdAtomFwHelper* biosHelper, UInt32 tableOffset);
    static IOReturn wrapGetVendorInfo(const void* self, AGDCVendorInfo_t* vendorInfo, size_t sizeofVendorInfo);
    static size_t   readVfctAtomBiosImage(void* self, UInt8* buffer, size_t bufferSize, bool strict = true);
    static size_t   readVramAtomBiosImage(void* self, UInt8* buffer, size_t bufferSize);
    static IOReturn readAtomBios(void* self);
    static AmdAtomPspDirectory* wrapCreatePspDirectory(AmdAtomFwHelper* biosHelper, UInt32 tableOffset);
};
