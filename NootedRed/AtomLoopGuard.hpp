// Guard the inspected Sonoma ATOM branch loop without inventing register values.
// All private ABI use is gated by the framebuffer UUID and entry signatures.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace DPRecovery
{
    struct AtomFrame {
        const uint8_t* table;
        const uint8_t* instruction;
        void* workspace;
        AtomFrame* parent;
    };
    static_assert(sizeof(AtomFrame) == 32 && offsetof(AtomFrame, parent) == 24);

    template<typename T> inline T atomLoad(const void* object, size_t offset)
    {
        T value;
        memcpy(&value, static_cast<const uint8_t*>(object) + offset, sizeof(value));
        return value;
    }

    // Borrowed native frames remain owned by the original interpreter. Redirect all
    // instruction pointers to EOT so its existing pop/free path unwinds them. Setting
    // its error-status field directly would bypass that cleanup and leak frames.
    inline bool unwindAtomFrames(void* context)
    {
        if (!context) { return false; }
        const auto* execution = atomLoad<const void*>(context, 0);
        if (!execution) { return false; }
        const auto* bios = atomLoad<const uint8_t*>(execution, 0x10);
        if (!bios) { return false; }
        const auto biosStart = reinterpret_cast<uintptr_t>(bios);
        static const uint8_t endOfTable = 0x5B;
        constexpr size_t maxDepth = 64;
        AtomFrame* frames[maxDepth];
        size_t count = 0;
        auto* frame = atomLoad<AtomFrame*>(context, 8);
        while (frame) {
            if (count == maxDepth || !frame->table) { return false; }
            for (size_t i = 0; i < count; ++i) {
                if (frames[i] == frame) { return false; }
            }
            const auto start = reinterpret_cast<uintptr_t>(frame->table);
            const auto ip = reinterpret_cast<uintptr_t>(frame->instruction);
            if (start < biosStart || start - biosStart > 0x10000 - 7) { return false; }
            const auto length = atomLoad<uint16_t>(frame->table, 0);
            if (length > 0x10000 - (start - biosStart)) { return false; }
            if (length < 7 || ip < start || ip - start < 6 || ip - start >= length) { return false; }
            frames[count++] = frame;
            frame = frame->parent;
        }
        if (!count) { return false; }
        // Commit only after the complete chain passes validation.
        for (size_t i = 0; i < count; ++i) { frames[i]->instruction = &endOfTable; }
        return true;
    }

    struct AtomExecution {
        uint64_t deadline;
        bool aborted{false};
        bool unwindRefused{false};
        uint32_t lastRegister{0};
        uint32_t lastValue{0};
        uint32_t tableOffset{0};
        uint32_t instructionOffset{0};
        uint32_t compareSource{0};
        uint32_t compareDestination{0};

        bool checkBranch(void* context, uint64_t now)
        {
            if (now < deadline || aborted || unwindRefused) { return false; }
            if (!context) { unwindRefused = true; return false; }
            auto* frame = atomLoad<AtomFrame*>(context, 8);
            if (!frame) { unwindRefused = true; return false; }
            const auto* execution = atomLoad<const void*>(context, 0);
            if (!execution) { unwindRefused = true; return false; }
            const auto* bios = atomLoad<const uint8_t*>(execution, 0x10);
            const auto base = reinterpret_cast<uintptr_t>(bios);
            const auto table = reinterpret_cast<uintptr_t>(frame->table);
            const auto ip = reinterpret_cast<uintptr_t>(frame->instruction);
            // readAtomBios uses a 64 KiB image on this inspected driver.
            if (!bios || table < base || table - base >= 0x10000 ||
                ip < table || ip - table >= 0x10000) {
                unwindRefused = true; return false;
            }
            tableOffset = static_cast<uint32_t>(table - base);
            instructionOffset = static_cast<uint32_t>(ip - table);
            compareSource = atomLoad<uint32_t>(context, 0x10);
            compareDestination = atomLoad<uint32_t>(context, 0x14);
            aborted = unwindAtomFrames(context);
            unwindRefused = !aborted;
            return aborted;
        }
    };

    // Each execution is used only by its owning kernel thread. Atomic ownership
    // permits simultaneous DP enables without sharing deadlines or abort state.
    // No allocations, locks held across native calls, or global forced success.
    template<size_t Count> class AtomThreadSlots {
    public:
        struct Slot {
            uintptr_t owner{0};
            AtomExecution* execution{nullptr};
            unsigned depth{0};
        };
        Slot* find(uintptr_t owner)
        {
            if (!owner) { return nullptr; }
            for (auto& slot : slots) {
                if (__atomic_load_n(&slot.owner, __ATOMIC_ACQUIRE) == owner) { return &slot; }
            }
            return nullptr;
        }
        Slot* acquire(uintptr_t owner)
        {
            if (!owner) { return nullptr; }
            if (auto* slot = find(owner)) { ++slot->depth; return slot; }
            for (auto& slot : slots) {
                uintptr_t empty = 0;
                if (__atomic_compare_exchange_n(&slot.owner, &empty, owner, false,
                                                __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
                    slot.execution = nullptr;
                    slot.depth = 1;
                    return &slot;
                }
            }
            return nullptr; // Exhaustion leaves native behavior unchanged.
        }
        void release(Slot* slot)
        {
            if (!slot || --slot->depth) { return; }
            slot->execution = nullptr;
            __atomic_store_n(&slot->owner, uintptr_t(0), __ATOMIC_RELEASE);
        }
    private:
        Slot slots[Count]{};
    };

    struct AtomEntryGuard { size_t offset; uint8_t bytes[32]; };
    constexpr AtomEntryGuard kAtomEntryGuards[] = {
        {0x5C9F0, {0x55,0x48,0x89,0xE5,0x48,0x83,0xEC,0x20,0xC7,0x45,0xF8,0x00,0x00,0x00,0x00,0x48,0x8B,0x47,0x10,0x48,0x89,0x45,0xF0,0x48,0x89,0x55,0xE0,0x48,0x8B,0x47,0x08,0x48}},
        {0x5C1B0, {0x55,0x48,0x89,0xE5,0x0F,0xB6,0x47,0x44,0x3C,0x05,0x74,0x05,0x3A,0x47,0x48,0x75,0x15,0x48,0x8B,0x47,0x08,0x48,0x8B,0x48,0x08,0x0F,0xB7,0x49,0x01,0x48,0x03,0x08}},
        {0x5C1F0, {0x55,0x48,0x89,0xE5,0x0F,0xB6,0x47,0x48,0x3C,0x01,0x74,0x05,0x3A,0x47,0x44,0x75,0x15,0x48,0x8B,0x47,0x08,0x48,0x8B,0x48,0x08,0x0F,0xB7,0x49,0x01,0x48,0x03,0x08}},
        {0x5C230, {0x55,0x48,0x89,0xE5,0x80,0x7F,0x48,0x01,0x48,0x8B,0x47,0x08,0x48,0x8B,0x48,0x08,0x75,0x06,0x48,0x83,0xC1,0x03,0xEB,0x07,0x0F,0xB7,0x49,0x01,0x48,0x03,0x08,0x48}},
        {0x1CAD6, {0x55,0x48,0x89,0xE5,0x41,0x57,0x41,0x56,0x53,0x50,0x89,0xF3,0x49,0x89,0xFE,0xC1,0xE3,0x02,0x48,0x8B,0x7F,0x10,0x48,0x8B,0x07,0xFF,0x90,0xD0,0x09,0x00,0x00,0x84}},
    };
    inline bool matchesAtomEntryPoints(const uint8_t* image, size_t size)
    {
        if (!image) { return false; }
        for (const auto& entry : kAtomEntryGuards) {
            if (entry.offset > size || sizeof(entry.bytes) > size - entry.offset ||
                memcmp(image + entry.offset, entry.bytes, sizeof(entry.bytes))) { return false; }
        }
        // The whole frame-creation/dispatch/EOT/free implementation must match,
        // not just the functions we route. This guard runs before any patching.
        constexpr size_t vmOffset = 0x5C400, vmSize = 0x367;
        if (vmOffset > size || vmSize > size - vmOffset) { return false; }
        uint64_t hash = 0xCBF29CE484222325ULL;
        for (size_t i = 0; i < vmSize; ++i) { hash = (hash ^ image[vmOffset + i]) * 0x100000001B3ULL; }
        return hash == 0x661912323CCE0E94ULL;
    }
} // namespace DPRecovery
