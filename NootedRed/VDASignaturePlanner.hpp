// Page-local planner for the explicitly opted-in standalone VA resolver.
// No allocation, page mutation or global per-boot suppression in this layer.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
namespace VDASignaturePlanner {
constexpr size_t PageSize = 4096;
constexpr size_t MaxSites = 24;
struct Site { size_t offset; const uint8_t* find; const uint8_t* replace; size_t size; };
struct Plan { Site sites[MaxSites]{}; size_t count{}; };
template <typename Signature>
inline bool build(const uint8_t* page, const Signature* signatures, size_t count, uint64_t pageOffset, Plan& plan) {
    plan.count = 0;
    if (!page || !signatures || !count || count > 16) { return false; }
    for (size_t i = 0; i < count; ++i) {
        const auto& s = signatures[i];
        if (!s.context || !s.mask || !s.find || !s.replace || !s.contextSize || s.contextSize > PageSize
            || !s.findSize || s.findSize != s.replaceSize || s.findSize > 64
            || s.patchOffset > s.contextSize || s.findSize > s.contextSize - s.patchOffset
            || !s.count || s.count > MaxSites || s.skip > MaxSites) { plan.count = 0; return false; }
        if (s.pageOffset != ~uint64_t(0) && s.pageOffset != pageOffset) { continue; }
        size_t matches = 0;
        for (size_t offset = 0; offset <= PageSize - s.contextSize; ++offset) {
            bool match = true;
            for (size_t j = 0; j < s.contextSize; ++j) {
                if ((page[offset+j] & s.mask[j]) != (s.context[j] & s.mask[j])) { match = false; break; }
            }
            if (!match) { continue; }
            const size_t site = offset + s.patchOffset;
            const bool stock = memcmp(page+site, s.find, s.findSize) == 0;
            const bool patched = memcmp(page+site, s.replace, s.replaceSize) == 0;
            if (!stock && !patched) { plan.count = 0; return false; }
            if (++matches > s.skip + s.count) { plan.count = 0; return false; }
            if (matches <= s.skip || patched) { continue; }
            if (plan.count == MaxSites) { plan.count = 0; return false; }
            for (size_t k = 0; k < plan.count; ++k) {
                const auto& previous = plan.sites[k];
                if (site < previous.offset+previous.size && previous.offset < site+s.findSize) {
                    plan.count = 0; return false;
                }
            }
            plan.sites[plan.count++] = {site,s.find,s.replace,s.findSize};
        }
    }
    return plan.count != 0;
}
}
