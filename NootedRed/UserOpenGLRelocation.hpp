// Page-local rel32 subset adapted from steve12311/NootedRed f8179e5.
// No dyld cache scanning or user-memory readers are needed for the GL file backend.
#pragma once
#include <IOKit/IOTypes.h>
#include <string.h>
namespace UserOpenGLRelocation {
constexpr UInt64 UserLimit = 0x0000800000000000ULL;
inline bool relativeTarget(UInt64 address, UInt32 offset, const UInt8* bytes, UInt64& target)
    {
        if (bytes == nullptr || address >= UserLimit - 4 || offset >= UserLimit - address - 4) { return false; }
        int displacement;
        memcpy(&displacement, bytes + offset, sizeof(displacement));
        const auto next = address + offset + 4;
        if (displacement < 0) {
            const auto magnitude = static_cast<UInt64>(-static_cast<long long>(displacement));
            if (next < magnitude) { return false; }
            target = next - magnitude;
        }
        else {
            if (next >= UserLimit || static_cast<UInt64>(displacement) >= UserLimit - next) { return false; }
            target = next + static_cast<UInt64>(displacement);
        }
        return true;
    }

inline bool setRelative(UInt8* bytes, UInt32 offset, UInt64 address, UInt64 target)
    {
        if (bytes == nullptr || address >= UserLimit - 4 || offset >= UserLimit - address - 4) { return false; }
        const auto next = address + offset + 4;
        if (next >= UserLimit || target >= UserLimit) { return false; }
        const auto magnitude = target >= next ? target - next : next - target;
        if (magnitude > (target >= next ? 0x7FFFFFFFULL : 0x80000000ULL)) { return false; }
        const auto signedValue =
            target >= next ? static_cast<long long>(magnitude) : -static_cast<long long>(magnitude);
        const auto value = static_cast<int>(signedValue);
        memcpy(bytes + offset, &value, sizeof(value));
        return true;
    }

struct Reference
    {
        UInt32 offset, image;
        UInt64 rva;
        UInt32 indirect;
    };

struct Function
    {
        UInt32           image;
        UInt64           rva;
        const UInt8*     original;
        UInt32           size;
        const Reference* originalRefs;
        UInt32           originalCount;
        const Reference* patchedRefs;
        UInt32           patchedCount;
    };

struct Location
    {
        UInt32 function, offset;
    };

inline bool skipped(UInt32 index, const Reference* refs, UInt32 count)
    {
        for (UInt32 i = 0; i < count; ++i) {
            if (index >= refs[i].offset && index - refs[i].offset < 4) { return true; }
        }
        return false;
    }
}
