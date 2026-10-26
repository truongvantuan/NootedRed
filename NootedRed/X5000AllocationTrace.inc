// Native arguments/results are forwarded exactly once. No allocation policy is changed.
// All diagnostic object reads are guarded by the complete installer identity/prefix checks.
namespace
{
    struct AllocationTraceContext {
        UInt64 thread{0};
        UInt64 event{0};
        UInt32 failures{0};
        UInt32 detailed{0};
        UInt32 kind{0}; // 1: physical allocation, 2: resource paging
    };
    struct AllocationTraceState {
        IOSimpleLock* lock{nullptr};
        bool ready{false};
        UInt64 nextEvent{0};
        UInt32 failures{0};
        UInt32 emitted{0};
        AllocationTraceContext contexts[GPUAllocationTraceData::ContextCount]{};
    };
    AllocationTraceState allocationTrace;

    size_t allocationTraceBegin(const UInt64 thread, const UInt32 kind = 2)
    {
        IOSimpleLockLock(allocationTrace.lock);
        size_t slot = GPUAllocationTraceData::ContextCount;
        for (size_t i = 0; i < GPUAllocationTraceData::ContextCount; ++i) {
            if (allocationTrace.contexts[i].event == 0) { slot = i; break; }
        }
        if (slot < GPUAllocationTraceData::ContextCount) {
            allocationTrace.contexts[slot] = {thread, ++allocationTrace.nextEvent, 0, 0, kind};
        }
        IOSimpleLockUnlock(allocationTrace.lock);
        return slot;
    }

    AllocationTraceContext allocationTraceEnd(const size_t slot)
    {
        AllocationTraceContext result{};
        if (slot >= GPUAllocationTraceData::ContextCount) { return result; }
        IOSimpleLockLock(allocationTrace.lock);
        result = allocationTrace.contexts[slot];
        allocationTrace.contexts[slot] = {};
        IOSimpleLockUnlock(allocationTrace.lock);
        return result;
    }
}

void X5000::installAllocationTrace(KernelPatcher& patcher, const size_t id,
                                  const mach_vm_address_t slide, const size_t size)
{
    if (!checkKernelArgument("-NRedAllocTrace")) { return; }
    NRed::singleton().setProp32("NRedAllocTraceRequested", 1);
    NRed::singleton().setProp32("NRedAllocTraceVersion", GPUAllocationTraceData::Version);
    CompatTarget::Identity identity{};
    if (currentKernelVersion().major() != 24
        || !CompatTarget::parseMachOIdentity(identity, reinterpret_cast<const UInt8*>(slide), size)
        || memcmp(identity.uuid, GPUAllocationTraceData::DriverUUID, sizeof(identity.uuid)) != 0) {
        NRed::singleton().setProp32("NRedAllocTraceRejected", 1);
        return;
    }
    PenguinWizardry::PatternRouteRequest requests[] = {
        {GPUAllocationTraceData::Methods[0].symbol, traceAllocatePhysical, this->orgAllocatePhysical},
        {GPUAllocationTraceData::Methods[1].symbol, traceResourcePageon, this->orgResourcePageon},
        {GPUAllocationTraceData::Methods[2].symbol, traceAllocateLargeBlocks, this->orgAllocateLargeBlocks},
    };
    static_assert(arrsize(requests) == arrsize(GPUAllocationTraceData::Methods));
    for (size_t i = 0; i < arrsize(requests); ++i) {
        const auto address = patcher.solveSymbol(id, requests[i].symbol, slide, size, true);
        patcher.clearError();
        if (size < sizeof(GPUAllocationTraceData::Methods[i].prefix) || address < slide
            || address - slide > size - sizeof(GPUAllocationTraceData::Methods[i].prefix)
            || memcmp(reinterpret_cast<const void*>(address), GPUAllocationTraceData::Methods[i].prefix,
                      sizeof(GPUAllocationTraceData::Methods[i].prefix)) != 0) {
            NRed::singleton().setProp32("NRedAllocTraceRejected", 2);
            return;
        }
        requests[i].from = address;
        requests[i].symbol = nullptr;
    }
    allocationTrace.lock = IOSimpleLockAlloc();
    if (allocationTrace.lock == nullptr) {
        NRed::singleton().setProp32("NRedAllocTraceRejected", 4);
        return;
    }
    UInt32 installed{0};
    for (size_t i = 0; i < arrsize(requests); ++i) {
        if (!requests[i].route(patcher, id, slide, size)) {
            patcher.clearError();
            NRed::singleton().setProp32("NRedAllocTraceRejected", 3);
            break;
        }
        installed |= 1U << i;
    }
    allocationTrace.ready = installed == GPUAllocationTraceData::RequiredRoutes;
    NRed::singleton().setProp32("NRedAllocTraceRoutes", installed);
    NRed::singleton().setProp32("NRedAllocTraceEnabled", allocationTrace.ready ? 1 : 0);
    SYSLOG("AllocTrace", "routes=0x%X version=%u limit=%u imageBase=0x%llX imageSize=0x%llX; native policy preserved", installed,
           GPUAllocationTraceData::Version, GPUAllocationTraceData::MaximumFailures,
           static_cast<UInt64>(slide), static_cast<UInt64>(size));
}

bool X5000::traceAllocatePhysical(void* const self)
{
    if (!allocationTrace.ready || self == nullptr) {
        return FunctionCast(traceAllocatePhysical, singleton().orgAllocatePhysical)(self);
    }
    const auto flags = getMember<UInt32>(self, GPUAllocationTraceData::AllocationFlagsOffset);
    const UInt64 thread = thread_tid(current_thread());
    const auto slot = allocationTraceBegin(thread, 1);
    const auto result = FunctionCast(traceAllocatePhysical, singleton().orgAllocatePhysical)(self);
    const auto context = allocationTraceEnd(slot);
    if (context.detailed != 0) {
        SYSLOG("AllocTrace", "physical-end tid=%llu physical=%llu failedRequests=%u sampled=%u result=%u flags=0x%X",
               thread, context.event, context.failures, context.detailed, result ? 1U : 0U, flags);
    }
    return result;
}

bool X5000::traceAllocateLargeBlocks(void* const self, void* const element, const UInt64 bytes,
                                    const UInt64 alignment, const UInt64 minimum, const UInt32 origin,
                                    const UInt32 operation, const bool noFixed)
{
    const auto result = FunctionCast(traceAllocateLargeBlocks, singleton().orgAllocateLargeBlocks)(
        self, element, bytes, alignment, minimum, origin, operation, noFixed);
    if (!allocationTrace.ready || result) { return result; }
    const UInt64 thread = thread_tid(current_thread());
    UInt64 outer{0};
    UInt64 physical{0};
    UInt32 serial{0};
    IOSimpleLockLock(allocationTrace.lock);
    size_t topPhysical = GPUAllocationTraceData::ContextCount;
    size_t topPaging = GPUAllocationTraceData::ContextCount;
    for (size_t i = 0; i < GPUAllocationTraceData::ContextCount; ++i) {
        if (allocationTrace.contexts[i].thread != thread) { continue; }
        if (allocationTrace.contexts[i].kind == 2 && allocationTrace.contexts[i].event > outer) {
            outer = allocationTrace.contexts[i].event;
            topPaging = i;
        }
        if (allocationTrace.contexts[i].kind == 1 && allocationTrace.contexts[i].event > physical) {
            physical = allocationTrace.contexts[i].event;
            topPhysical = i;
        }
    }
    if (topPhysical < GPUAllocationTraceData::ContextCount) { ++allocationTrace.contexts[topPhysical].failures; }
    if (topPaging < GPUAllocationTraceData::ContextCount) { ++allocationTrace.contexts[topPaging].failures; }
    ++allocationTrace.failures;
    if (allocationTrace.emitted < GPUAllocationTraceData::MaximumFailures) {
        serial = ++allocationTrace.emitted;
        if (topPhysical < GPUAllocationTraceData::ContextCount) { ++allocationTrace.contexts[topPhysical].detailed; }
        if (topPaging < GPUAllocationTraceData::ContextCount) { ++allocationTrace.contexts[topPaging].detailed; }
    }
    IOSimpleLockUnlock(allocationTrace.lock);
    if (serial != 0) {
        const auto process = current_proc();
        const int pid = process != nullptr ? proc_pid(process) : 0;
        char name[32]{};
        if (pid > 0) { proc_name(pid, name, sizeof(name)); }
        name[sizeof(name) - 1] = '\0';
        SYSLOG("AllocTrace", "allocation-fail serial=%u tid=%llu physical=%llu outer=%llu pid=%d name=%s bytes=%llu align=%llu minBlock=%llu origin=%u operation=%u noFixed=%u caller=0x%llX",
               serial, thread, physical, outer, pid, name, bytes, alignment, minimum, origin, operation, noFixed ? 1U : 0U,
               static_cast<UInt64>(reinterpret_cast<uintptr_t>(__builtin_return_address(0))));
        if (serial <= 4) {
            void* frames[12]{};
            const auto count = OSBacktrace(frames, arrsize(frames));
            for (unsigned i = 0; i < count && i < arrsize(frames); ++i) {
                SYSLOG("AllocTrace", "backtrace serial=%u frame=%u pc=0x%llX", serial, i,
                       static_cast<UInt64>(reinterpret_cast<uintptr_t>(frames[i])));
            }
        }
        if (serial == GPUAllocationTraceData::MaximumFailures) {
            SYSLOG("AllocTrace", "detail limit reached; later failures are not individually logged");
        }
    }
    return result;
}

void X5000::traceResourcePageon(void* const self, void* const event, const bool flag, const UInt64 options)
{
    if (!allocationTrace.ready || self == nullptr) {
        FunctionCast(traceResourcePageon, singleton().orgResourcePageon)(self, event, flag, options);
        return;
    }
    const auto before = getMember<UInt32>(self, GPUAllocationTraceData::ResourceFlagsOffset);
    const UInt64 thread = thread_tid(current_thread());
    const auto slot = allocationTraceBegin(thread);
    FunctionCast(traceResourcePageon, singleton().orgResourcePageon)(self, event, flag, options);
    const auto context = allocationTraceEnd(slot);
    if (context.detailed != 0) {
        // Native pageon returns void. Record state bytes; never invent a success return.
        SYSLOG("AllocTrace", "pageon-end tid=%llu outer=%llu failures=%u sampled=%u flagsBefore=0x%X flagsAfter=0x%X options=0x%llX caller=0x%llX",
               thread, context.event, context.failures, context.detailed, before,
               getMember<UInt32>(self, GPUAllocationTraceData::ResourceFlagsOffset), options,
               static_cast<UInt64>(reinterpret_cast<uintptr_t>(__builtin_return_address(0))));
    }
}
