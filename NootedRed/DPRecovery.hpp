// Experimental DisplayPort receiver wake sequencing.
// See docs/DisplayPort-Recovery.md for binary provenance and verification limits.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace DPRecovery
{
    constexpr uint32_t kSetPower = 0x600;
    constexpr uint8_t kPowerMask = 7;
    constexpr uint8_t kD0 = 1;
    constexpr uint8_t kD3 = 2;
    constexpr uint8_t kD3AuxOn = 5;
    constexpr unsigned kMaxAttempts = 3;
    constexpr uint32_t kSettleMs = 2;
    constexpr int kAuxSuccess = 1; // enum dc_status, not IOReturn.
    constexpr uint32_t kDisplayPort = 0x20;

    enum class State : uint32_t {
        AlreadyAwake = 1, Woken = 2, ReadFailed = 3,
        UnsupportedPower = 4, WakeFailed = 5,
    };

    struct Result {
        State state;
        uint8_t before;
        uint8_t after;
        unsigned attempts;
    };

    // Inject AUX and delay operations so the production policy can be tested on a host.
    // No raw MMIO, fabricated register values, or success without readback.
    template<typename Read, typename Write, typename Delay>
    Result wakeReceiver(Read read, Write write, Delay delay)
    {
        uint8_t power = 0;
        unsigned reads = 0;
        for (; reads < kMaxAttempts; ++reads) {
            if (read(kSetPower, &power, 1) == kAuxSuccess) { break; }
            if (reads + 1 < kMaxAttempts) { delay(kSettleMs); }
        }
        if (reads == kMaxAttempts) { return {State::ReadFailed, 0, 0, reads}; }
        const uint8_t before = power;
        if ((power & kPowerMask) == kD0) { return {State::AlreadyAwake, before, power, 0}; }
        if ((power & kPowerMask) != kD3 && (power & kPowerMask) != kD3AuxOn) {
            return {State::UnsupportedPower, before, power, 0};
        }
        // Preserve reserved bits. Some monitors retain D3 across their soft power button.
        const uint8_t requested = (power & ~kPowerMask) | kD0;
        for (unsigned attempt = 1; attempt <= kMaxAttempts; ++attempt) {
            const int status = write(kSetPower, &requested, 1);
            // Also allow AUX to recover after a failed write, before retrying.
            delay(kSettleMs);
            if (status == kAuxSuccess && read(kSetPower, &power, 1) == kAuxSuccess &&
                (power & kPowerMask) == kD0) {
                return {State::Woken, before, power, attempt};
            }
        }
        return {State::WakeFailed, before, power, kMaxAttempts};
    }

    // The three private entry points were inspected in the installed Sonoma 23J631
    // SystemKernelExtensions.kc. Offsets are relative to this kext's __TEXT/header.
    constexpr size_t kEnablePhyOffset = 0xC9319;
    constexpr size_t kReadDpcdOffset = 0x12471F;
    constexpr size_t kWriteDpcdOffset = 0x124884;
    constexpr uint8_t kFramebufferUuid[] = {
        0x2A,0x0E,0xC5,0xC3,0x73,0x55,0x30,0x63,0xBC,0xCE,0xE1,0x5C,0xF7,0xE0,0x2A,0x0C,
    };
    constexpr uint8_t kEnablePhyPrologue[] = {
        0x55,0x48,0x89,0xE5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x48,0x83,0xEC,
        0x28,0x49,0x89,0xCF,0x89,0x55,0xD0,0x89,0x75,0xD4,0x48,0x89,0xFB,0x48,0x8B,0x8F,
    };
    constexpr uint8_t kReadDpcdPrologue[] = {
        0x55,0x48,0x89,0xE5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x48,0x83,0xEC,
        0x38,0x41,0x89,0xCD,0x49,0x89,0xD7,0x41,0x89,0xF4,0x43,0x8D,0x04,0x2C,0xFF,0xC8,
    };
    constexpr uint8_t kWriteDpcdPrologue[] = {
        0x55,0x48,0x89,0xE5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x48,0x83,0xEC,
        0x18,0x48,0x89,0x55,0xC8,0x85,0xC9,0x74,0x7D,0x89,0xCB,0x41,0x89,0xF7,0x48,0x89,
    };

    inline uint32_t little32(const uint8_t* p)
    {
        return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
               (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
    }

    inline bool matchesFramebuffer(const uint8_t* image, size_t size)
    {
        if (!image || size < 32 || little32(image) != 0xFEEDFACF ||
            little32(image + 4) != 0x01000007) { return false; }
        const size_t commandBytes = little32(image + 20);
        const uint32_t commands = little32(image + 16);
        if (commandBytes > size - 32 || commands > commandBytes / 8) { return false; }
        const size_t end = 32 + commandBytes;
        size_t at = 32;
        bool uuidMatches = false;
        for (uint32_t i = 0; i < commands; ++i) {
            if (at > end || end - at < 8) { return false; }
            const uint32_t command = little32(image + at);
            const size_t bytes = little32(image + at + 4);
            if (bytes < 8 || bytes > end - at) { return false; }
            if (command == 0x1B) { // LC_UUID
                if (bytes != 24 || uuidMatches ||
                    memcmp(image + at + 8, kFramebufferUuid, sizeof(kFramebufferUuid))) { return false; }
                uuidMatches = true;
            }
            at += bytes;
        }
        if (!uuidMatches || at != end) { return false; }
        struct Guard { size_t offset; const uint8_t* bytes; size_t count; };
        const Guard guards[] = {
            {kEnablePhyOffset, kEnablePhyPrologue, sizeof(kEnablePhyPrologue)},
            {kReadDpcdOffset, kReadDpcdPrologue, sizeof(kReadDpcdPrologue)},
            {kWriteDpcdOffset, kWriteDpcdPrologue, sizeof(kWriteDpcdPrologue)},
        };
        for (const auto& guard : guards) {
            if (guard.offset > size || guard.count > size - guard.offset ||
                memcmp(image + guard.offset, guard.bytes, guard.count)) { return false; }
        }
        return true;
    }
} // namespace DPRecovery
