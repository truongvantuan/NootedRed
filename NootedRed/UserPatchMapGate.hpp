// Adapted from steve12311 6fb1aa6. Serialize private patches by address space.
// Registry locking never covers VM work; same-thread reentry fails closed.
#pragma once

namespace UserPatchMapGate
{
    template<unsigned Capacity>
    struct Registry
    {
        static_assert(Capacity > 0);
        void* keys[Capacity]{};
        void* owners[Capacity]{};
        unsigned active{0}, peak{0};
    };

    template<unsigned Capacity>
    class Lease
    {
        Registry<Capacity>& registry;
        IOLock*             lock;
        void*               key;
        unsigned            slot{Capacity};

    public:
        Lease(Registry<Capacity>& registry, IOLock* lock, void* key, void* owner) : registry(registry), lock(lock), key(key)
        {
            if (!lock || !key || !owner) { return; }
            IOLockLock(lock);
            for (;;) {
                unsigned free = Capacity;
                bool busy = false;
                // A nested shared-region hook must never wait for its own transaction.
                for (unsigned i = 0; i < Capacity; ++i) {
                    if (registry.owners[i] == owner) { IOLockUnlock(lock); return; }
                }
                for (unsigned i = 0; i < Capacity; ++i) {
                    if (registry.keys[i] == key) { busy = true; break; }
                    if (!registry.keys[i] && free == Capacity) { free = i; }
                }
                if (!busy && free != Capacity) {
                    registry.keys[free] = key;
                    registry.owners[free] = owner;
                    if (++registry.active > registry.peak) { registry.peak = registry.active; }
                    slot = free;
                    break;
                }
                IOLockSleep(lock, busy ? key : static_cast<void*>(&registry), THREAD_UNINT);
            }
            IOLockUnlock(lock);
        }

        ~Lease()
        {
            if (slot == Capacity) { return; }
            IOLockLock(lock);
            registry.keys[slot] = nullptr;
            registry.owners[slot] = nullptr;
            --registry.active;
            IOLockWakeup(lock, key, false);
            IOLockWakeup(lock, &registry, false);
            IOLockUnlock(lock);
        }

        explicit operator bool() const { return slot != Capacity; }
        Lease(const Lease&) = delete;
        Lease& operator=(const Lease&) = delete;
        Lease(Lease&&) = delete;
        Lease& operator=(Lease&&) = delete;
    };
}
