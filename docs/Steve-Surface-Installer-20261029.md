# Private SRD/scratch installer checkpoint

This candidate connects the verified 24H232 surface profile to our existing
shared-region hook. It is experimental and off by default. It has not been
installed or hardware-tested. The current internal EFI still runs f238c89,
with Phantom disabled and neither experimental flag present.

The 07:22 boot on 29 October loads RELEASE UUID
23D75465-1596-306B-A9B7-0AFFA9867F77; Phantom is absent. No newer saved panic
report was found during the baseline check. The user confirms normal desktop,
menus, USB, speaker, Wi-Fi and Bluetooth. This establishes a boot baseline,
not video/compute output or sleep/wake acceptance.

## Selection and ownership

`-NRedSurfaceFix` selects this path only with the existing rendering option,
qualified graphics profile, Darwin 24, build 24H232 and one of the six generated
APU profiles. Actual cache UUID, complete functions, external targets, init
constant and named native dump stub remain mandatory. FairPlay clients skip
the new path. GLFix off and unknown OS/build/device retain existing behavior.

One existing shared-region syscall hook calls native first and takes the
existing per-map lease. No second hook, coordinator, address-space ledger or
map-destruction route is added. This is unrelated to video-mode selection;
`-NRedVCNSafety` remains a separate experimental option.

When SubmitGuard is requested, its actual entry/payload and RX permissions must
verify before SRD/scratch runs. Its installation now returns that verification
result instead of inferring readiness from a published marker. A failed guard
still permits the pre-existing independent LegacyBlend and codec paths. An
explicit SubmitGuard opt-out is respected; it does not silently re-enable the
guard or LegacyBlend through the new surface option.

The planner accepts wholly native SRD/scratch sites, including an already applied
known local LegacyBlend gate, or a fully installed surface set. Other mixed
states reject. With LegacyBlend disabled its gate is unowned and preserved.
An unchanged gate is checked but receives no additional write or COW. This
retains the existing native page owner and avoids undoing its gate on rollback.

The adapter allocates both planning workspaces on the heap, queries leaf VM
permissions, and repeats complete function/reference/extra-identity validation
immediately before COW. It uses the same VM permission/copy helpers and checked
transaction executor as the codec adapter. All writes receive chunked readback;
RX and original maximum protections must be restored. Failed rollback halts new
surface transactions for the boot. It does not claim to undo prior installations
in other processes. No persistent raw map-pointer identity is retained.

These leases serialize our installers; they do not stop unrelated application
threads or third-party writers. Runtime startup and concurrency acceptance are
still required. A halt marker prohibits further hardware testing.

## Host and reference evidence

- 201 exact planner cases cover six APUs, every native/patched combination,
  both LegacyBlend options, fresh-plan equality and identity rejection.
- 65,536 policy-ID cases, 24 build/option cases and 32 actual installer cases
  run under fatal ASan/UBSan. Installer cases cover every write/protect failure,
  silent write corruption, partial rollback corruption, changed complete
  function bytes before publication, permission/query/submap failures,
  allocation failure, existing/disabled blend ownership and mixed states.
- The existing codec adapter's 241 fault cases still pass after sharing its
  VM backend. The actual shared-region wrapper tests native results, FairPlay,
  surface-only routing, deferred SRD after SubmitGuard failure, fallback and halt.
- All 49 workflow host checks pass. RELEASE builds successfully. The measured
  direct call chain across all three translation units is 4344 bytes, largest
  reachable frame 1576 bytes and wrapper frame 72 bytes. Native kernel functions
  and indirect callbacks are excluded; this is not a total kernel stack bound.
- The reference generator reproduces the data and embedded page-hash checks.
  A read-only file-cache test passes all six APUs and both blend options twice.
  About 11 ms for both passes includes file-reader overhead and is not a live
  kernel startup or GPU benchmark.

Evidence: build/steve-surface-installer-20261029/, including regression-final,
stack-final, live-plan.log and boot-baseline. Reference/payload CPU evidence is
also described in Steve-Surface-24H232-20261028.md.

## Passive post-boot probe

Build with `sh tools/build-surface-probe.sh`. Its binary reads only its own
shared-cache mappings; it creates no GPU objects. It verifies complete functions,
typed references, selected site bytes and actual leaf RX permissions.

`surface_probe --require-installed` must fail when only native/legacy state is
present, and pass only for the fully installed surface set. A basic VM-region
query can describe an enclosing submap; the probe uses bounded recursive leaf
queries, matching the kernel adapter. The initial basic-region experiment is
retained separately and does not establish a permission fault.

The current baseline correctly accepts the reference with leaf RX and reports
fully_installed=false. This must not be reported as hardware feature success.
The probe targets this machine's 0x1636 profile. Use `--no-blend` only when the
corresponding local option is disabled.

Next acceptance: controlled diagnostic boot, actual loaded UUID and bytes,
normal Metal/compute/GL/video workloads, process-startup latency, user-visible
output, and genuine sleep/wake. No malformed GPU inputs are submitted by these
tools. The wider fork selection, including overnight cache/framework changes,
remains open.
