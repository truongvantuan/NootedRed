// Verified private user-code writes shared by SubmitGuard and LegacyBlend.
#pragma once
#include <IOKit/IOTypes.h>
#include <libkern/libkern.h>

namespace UserCodePatch {
    struct Result {
        bool applied;
        // Only a verified original entry with RX protection permits freeing a new trampoline.
        bool originalRestored;
    };

    template <typename Memory>
    Result write(Memory& memory, UInt64 address, const UInt8* original, const UInt8* target, size_t size)
    {
        constexpr size_t maxSize = 128, pageSize = 4096;
        UInt8 observed[maxSize];
        if (size == 0 || size > maxSize || (address & (pageSize - 1)) + size > pageSize) {
            return {false, true};
        }
        if (!memory.read(address, observed, size) || memcmp(observed, original, size) != 0
            || !memory.isRX(address)) {
            return {false, true}; // Nothing written by this transaction.
        }
        if (memory.writable(address)) {
            const bool written = memory.write(address, target, size);
            const bool verified = written && memory.read(address, observed, size)
                                  && memcmp(observed, target, size) == 0;
            const bool protectedRX = memory.executable(address);
            if (verified && protectedRX && memory.isRX(address)) { return {true, false}; }
        }
        // A failed copyout may have written a prefix. Roll back and verify before releasing its target.
        if (memory.writable(address)) {
            memory.write(address, original, size);
        }
        memory.executable(address);
        const bool restored = memory.read(address, observed, size)
                              && memcmp(observed, original, size) == 0 && memory.isRX(address);
        return {false, restored};
    }
}
