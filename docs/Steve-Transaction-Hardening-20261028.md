# Private cache transaction hardening candidate

This is the first selected adaptation from steve12311 commit
`6fb1aa6df07243c44541cbd3ccf5371804c4a804`, on top of our merged Weachy
1.2.0 (`b340e7b`). It does not import the fork's video codec guards, shared-cache
resolver or SRD/scratch changes. Their review and outstanding 24H232 reference
requirements remain in `build/fork-audit/steve-20261028/REVIEW.md`.

## Behavior

Our existing `_shared_region_check_np` hook still calls the native syscall first
and returns its result/output unchanged. After successful native completion,
SubmitGuard and LegacyBlend private-page installers acquire one address-space
lease. Different vm_maps can patch concurrently; tasks sharing a vm_map serialize.
A fixed 64-entry registry requires no per-request allocation. Its IOLock covers
only short registry operations; it is not held while reading/faulting user pages,
allocating VM, writing, restoring protection or reporting properties. Waiting
releases the registry lock. RAII releases the lease and wakes both same-map and
capacity waiters on every return path.

The adapted helper also tracks the owning thread. Same-thread nested hook entry
returns without patching instead of waiting for itself. Native syscall results
are still forwarded. Null map, thread or unavailable lock cannot start a write.
The lock is allocated before hook publication and kept for the boot lifetime,
including route failure, so no hook can observe a freed lock.

`NRedUserMapGateRevision=1` identifies this implementation. A rejected/missing
lease sets `NRedUserMapGateRejected=1`; it is a diagnostic, not success evidence.
No PID or previous application counter replaces current patch validation.
Current/max RX checks, exact cache and page checks, rollback rules, reachable
payload retention, GL ownership, VCN policy and no-poll teardown are unchanged.
No second hook is added.

This is preventive concurrency hardening; no captured fault on this machine has
been proven to result from a same-map installation race. The fork's global VCN
scan lock was never present in our hook, so no removal of that global bottleneck
or measured speed gain is claimed here.

## Checks

The actual local hook and lease helper execute under ASan/UBSan (fatal sanitizer
errors) and ThreadSanitizer. Cases cover independent-map progress with a stalled
transaction, mutual exclusion for tasks sharing a map, capacity/wakeup, 1600
concurrent leases, owner reentry, missing inputs, native-error/output forwarding,
disabled features and null arguments. Existing real installer/rollback/permission
and OS cache tests remain enabled. No GPU work is submitted by host checks.

The new stack tool recompiles UserPatches using the RELEASE build's exact xmake
compiler options with `-fstack-usage` and LLVM IR. For the candidate:

- Shared-region entry: 72 bytes.
- Largest reachable direct internal frame: 616 bytes.
- Longest visible direct internal chain: 1208 bytes.

Limits are entry 512, frame 2048 and visible chain 8192 bytes. These are not a
whole-kernel bound: native syscall, indirect callbacks, VM/IOKit, copyin/out and
lock internals are excluded. The compiler flags and raw stack/IR reports are
saved, not inferred from a Debug host harness.

Build and regression evidence: `build/steve-map-gate-20261028/`.
The intended artifact is RELEASE. The installation replaces only NootedRed in
the internal EFI after a full verified backup, preserves config/boot args and all
other kexts, and requires a manual reboot before runtime verification.

After boot, require the new build UUID and gate revision, verify private patch
bytes and NotificationCenter integrity, inspect rejection/error and GPU logs,
then run bounded native rendering tests if the baseline is clean. Desktop,
startup behavior, devices and sleep/wake need separate user confirmation.
