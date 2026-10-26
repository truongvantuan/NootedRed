// 独立 OpenGL 文件在签名验证后修正内存页；不修改磁盘文件或验证结果。
#include <Headers/kern_mach.hpp>
#include <Headers/kern_util.hpp>
#include <NRed.hpp>
#include <UserOpenGL.hpp>
#include <UserOpenGLResolver.hpp>
#include <kern/thread_call.h>

namespace
{

    const UserOpenGLData::Device* device{nullptr};
    thread_call_t                 reportCall{nullptr};
    UInt32                        appliedMask{0}, dynamicMask{0}, errorMask{0};
    bool                          allowDynamic{true}, forceDynamic{false};

    // 仅在命中或写入失败后排队发布诊断；初始化不启动工作线程。
    __attribute__((noinline)) void publish(thread_call_param_t, thread_call_param_t)
    {
        const auto applied = __atomic_load_n(&appliedMask, __ATOMIC_RELAXED);
        const auto dynamic = __atomic_load_n(&dynamicMask, __ATOMIC_RELAXED);
        const auto errors  = __atomic_load_n(&errorMask, __ATOMIC_RELAXED);
        auto&      nred    = NRed::singleton();
        nred.setProp32("NRedOpenGLSEApplied", (applied & 1) != 0);
        nred.setProp32("NRedGLBudgetApplied", (applied & 4) != 0);
        if (applied) { nred.setProp32("NRedGLFixGLApplied", 1); }
        nred.setProp32("NRedOpenGLDualQuadApplied", (applied & 2) != 0);
        nred.setProp32("NRedOpenGLDynamicApplied", dynamic == 3);
        nred.setProp32("NRedOpenGLWriteRejected", (errors & 1) != 0);
        nred.setProp32("NRedOpenGLRestoreFailed", (errors & 2) != 0);
    }

    void report(UInt32& mask, UInt32 bits)
    {
        if ((__atomic_fetch_or(&mask, bits, __ATOMIC_RELAXED) & bits) != bits) { thread_call_enter(reportCall); }
    }

    bool restoreWriting()
    {
        if (MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) == KERN_SUCCESS) { return true; }
        // Lilu 失败时也会释放锁；恢复重试必须重新配对加锁，不能重复解锁。
        if (MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) { return false; }
        return MachInfo::setKernelWriting(false, KernelPatcher::kernelWriteLock) == KERN_SUCCESS;
    }

    __attribute__((noinline)) void patchBlock(const UInt8* bytes, UInt64 offset, UInt32 kind)
    {
        UserOpenGLResolver::Resolved plan;
        if (!UserOpenGLResolver::resolvePage(*device, bytes, offset, kind, plan, allowDynamic, forceDynamic)) { return; }
        if (!plan.alreadyPatched) {
            if (MachInfo::setKernelWriting(true, KernelPatcher::kernelWriteLock) != KERN_SUCCESS) {
                report(errorMask, 1);
                return;
            }
            const bool fresh = memcmp(bytes + plan.offset, plan.original, plan.size) == 0;
            if (fresh) { memcpy(const_cast<UInt8*>(bytes) + plan.offset, plan.patched, plan.size); }
            if (!restoreWriting()) {
                report(errorMask, 2);
                return;
            }
            if (!fresh) { return; }
        }
        if (plan.dynamic) { report(dynamicMask, 1U << kind); }
        report(appliedMask, 1U << kind);
    }

} // namespace

// One existing UserPatches hook owns validation, vnode checks, GL budget and VDA dispatch.
// This module never installs another code-signing hook.
void UserOpenGL::init(UInt32 darwin, UInt32 deviceID, bool dynamic, bool force)
{
    device = UserOpenGLData::findDevice(darwin, deviceID);
    if (!device) { return; }
    allowDynamic = dynamic;
    forceDynamic = force;
    reportCall = thread_call_allocate_with_options(publish, nullptr, THREAD_CALL_PRIORITY_KERNEL,
                                                   THREAD_CALL_OPTIONS_ONCE);
    if (!reportCall) {
        NRed::singleton().setProp32("NRedOpenGLRejected", 1);
        return;
    }
    NRed::singleton().setProp32("NRedOpenGLRevision", 5);
    NRed::singleton().setProp32("NRedOpenGLPageLocal", 1);
    NRed::singleton().setProp32("NRedOpenGLEnabled", 1);
}

__attribute__((noinline)) void UserOpenGL::patchPage(const void* data, UInt64 offset)
{
    if (!device || !reportCall || !data) { return; }
    for (UInt32 kind = 0; kind < 2; ++kind) {
        patchBlock(static_cast<const UInt8*>(data), offset, kind);
    }
}

void UserOpenGL::reportBudgetResult(bool applied, bool restored)
{
    if (!reportCall) { return; }
    if (!restored) { report(errorMask, 2); }
    else if (applied) { report(appliedMask, 4); }
}
