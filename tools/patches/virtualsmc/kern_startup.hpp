// Single-transition publication gate for VirtualSMC's two startup producers.
#pragma once
#include <stdint.h>
#include <stdatomic.h>

namespace VSMCStartup {
    static constexpr uint32_t ServicingReady = 1U;
    static constexpr uint32_t MmioReady = 2U;
    static constexpr uint32_t AllReady = ServicingReady | MmioReady;

    // The last producer acquires the other producer's completed initialization
    // and alone owns publication. Repeated notifications cannot publish twice.
    inline bool arrive(_Atomic(uint32_t) *state, uint32_t ready) {
        const auto previous = atomic_fetch_or_explicit(state, ready, memory_order_acq_rel);
        return (previous & AllReady) != AllReady && ((previous | ready) & AllReady) == AllReady;
    }
}
