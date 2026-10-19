// VDA / Hardware Video Decode Policy
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

#include <DeviceProfile.hpp>
#include <Headers/kern_util.hpp>
#include <NRed.hpp>
#include <VDA.hpp>
#include <libkern/OSTypes.h>

static VDA moduleInstance;

namespace
{

    const char* const kBootArgVDA = "-NRedVDA";

}    // namespace

VDA& VDA::singleton() { return moduleInstance; }

void VDA::init()
{
    this->requested = checkKernelArgument(kBootArgVDA);

    if (!this->requested) {
        DBGLOG("VDA", "Hardware video decode is disabled; add -NRedVDA to opt in (experimental)");
        return;
    }

    DBGLOG("VDA", "-NRedVDA is set, resolving the media policy after device detection");
}

void VDA::processPatcher()
{
    // Never null: DeviceProfile::current() falls back to the generic profile for unknown devices.
    const auto* const profile = DeviceProfile::current();

    const auto& media         = profile->media;
    const auto  vcnGeneration = static_cast<UInt32>(media.vcnGeneration);

    DBGLOG("VDA", "%s: VCN %u.%u, firmware %s, ring 0x%X, fence 0x%X, H.264=%u HEVC=%u AV1=%u", profile->name,
           vcnGeneration >> 8, vcnGeneration & 0xFF, media.vcnFirmware != nullptr ? media.vcnFirmware : "none",
           media.vcnRingSize, media.vcnFenceSize, static_cast<UInt32>(media.decode.h264),
           static_cast<UInt32>(media.decode.hevc), static_cast<UInt32>(media.decode.av1));

    // Phase 1 has no engine bring-up, so a request cannot be honoured yet.  This is user-visible because
    // -NRedVDA is an explicit opt-in; software decode keeps working and no media engine is touched.
    if (!this->requested) { return; }

    if (!this->mediaEnginesEnabled()) {
        SYSLOG("VDA",
               "-NRedVDA is set, but hardware decode is not available for %s yet (UVD0=%u VCE=%u VCN0=%u); software "
               "decode stays in use",
               profile->name, static_cast<UInt32>(media.hasUVD0), static_cast<UInt32>(media.hasVCE),
               static_cast<UInt32>(media.hasVCN0));
    }

    NRed::singleton().setProp32("NRedVDARequested", static_cast<UInt32>(this->requested));
    NRed::singleton().setProp32("NRedVDAMediaEnabled", static_cast<UInt32>(this->mediaEnginesEnabled()));
    NRed::singleton().setProp32("NRedVCNGeneration", vcnGeneration);
}
