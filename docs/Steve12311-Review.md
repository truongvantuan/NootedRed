# steve12311 fork review, 2026-10-22

For the newer fork commits, selected safety changes and candidate builds, see
[the 25 October comparison](Steve12311-Review-20261025.md). The findings below
describe the earlier pinned source and are not a current migration checklist.

This is the historical source-review stage. Later corrected blend semantics,
transaction/installer safety and encoder work are covered by the current
[validated RELEASE report](Validated-Release-20261023.md); the migration priorities
below describe the findings at review time, not outstanding deployment steps.

Reviewed [master at 128b98067387e0ee49692d424b8543de5739bd6a](https://github.com/steve12311/NootedRed/tree/128b98067387e0ee49692d424b8543de5739bd6a)
against our combined master `1e3c77e` plus the local NotificationCenter GLFix guards.
No steve runtime code has been imported or installed by this review.

The shared ancestor is `8e93e82`. Steve has 12 subsequent commits, touching 95 files
relative to that ancestor. A direct tree comparison with our combined master touches
369 files, with about 21,829 insertions and 39,327 deletions: this is a substantial
alternative implementation, not a small update to our current Weachy/xiaot-evo merge.
Its Xcode/submodule build also differs from our AppleForge/xmake build.

## Findings and migration priority

| Area | Verified source difference | Relevance to our machine and migration decision |
| --- | --- | --- |
| Shared-cache patch transactions | `UserSurfaceSync.cpp` checks existing trampoline destination, complete payload, continuation and RX protection; restores original entry after failures; frees unreferenced allocations but retains a target page when entry rollback cannot be confirmed. | Highest priority to adapt into our SubmitGuard installer after the GLFix boot test. Our installer currently checks only the six-byte jump prefix for an already-patched entry and lacks equivalent partial-write rollback. |
| LegacyBlend on macOS 14/15 | Exact cache UUID/full-page profiles; only the hardware capability gate changes, preserving `dualSource || !allowRBPlus`. | High priority for Sequoia. Our Weachy-derived allow offsets are wrong in both reference pages: Sonoma 0x1DB contains `0f ba 64`, whereas the setcc is at 0x1E1; Sequoia 0x185 contains `40 fe ff`, whereas setcc is at 0x198. Gate-only semantics avoid globally forcing the dual-quad bit. This offset finding does not by itself explain every missing Applied property or GPU reset. |
| Private COW user patching | Preflights complete pages/functions, stages writes in each process, restores permissions and rolls back multi-page failures. | Prefer this architecture for Metal/VA cache patches. Preserve our guarded OpenGL path separately; replacing the entire module would discard existing behavior. |
| SubmitGuard payload | The generated payload and our `UserSubmitGuard.hpp` payload are both 307 bytes and have SHA-256 `b54c939ccf8a855cc784d5a569d40b1c3912cbebf0eec9fbcb826c472bf94fc6`. | Already present byte-for-byte. Port the safety harness and installer improvements, not a duplicate payload claimed as a new performance fix. |
| Compute submission vtable | Adds two Itanium header slots before using the object's vtable address point and verifies that the selected entry equals the resolved original method. | Candidate for the compute-reset investigation. Our hook is currently deliberately disabled. Re-enable only as a separate guarded experiment after verifying our kernel driver slot and ABI; the address-point correction alone does not prove GPU recovery. |
| ImmediateSync, shared SRD and ComputeScratch | Device-specific initialization and scratch sizing, plus bounded dynamic cache/function matching. | Current runtime enables these on Darwin 25 only. They are not a Sequoia 15.8.1 fix. Do not transplant Tahoe addresses or turn these on in our EFI. |
| VCN encode | Source-texture pitch handling and firmware 48-byte feedback stride, with encode/decode pixel-readback tools. | Our Sonoma/Sequoia/Tahoe tables already contain the 48-byte feedback allocation and AVC/HEVC consumer patches. The source-pitch consumer change and stronger output verification are candidates; current Steve legacy 14/15 profiles explicitly omit unsupported pitch/swizzle patches. Native Sequoia consumers must be inspected before porting those changes. |
| VCN device coverage | Explicit 1636/1638/164C/15E7 VCN2 capability and ABI checks; VCN1 excluded. | Our existing combined profile already covers these four VCN2 IDs. Benefit is transaction/ABI testing and implementation details, not newly enabling our Renoir PCI ID. |
| EC backlight service | Separates WMI/EC work from AMD display callbacks using an independent service/work loop and atomic requests. | Useful for applicable laptops. Our HP desktop and external display have no demonstrated need for this firmware-specific brightness backend. Leave it out of this machine's EFI. |

The current host's dyld cache UUID, read from the live main cache header, is
`42EC2890-BC40-317E-BB27-45142BFF7F26`, matching Steve's Sequoia reference profile.
UUID agreement is only an initial prerequisite: complete page, ABI and patch checks
must still pass. The fork's latest macOS 14/15 integration explicitly has pending
hardware acceptance; its earlier Cezanne/Tahoe reports are not validation for our Renoir.

## Installed Sequoia compute vtable follow-up

The standalone kernel driver executable is absent on this host, so the upstream
vtable test cannot use its original file path. A read-only check instead parsed
the installed SystemKernelExtensions.kc and independently verified the prelink
pointer bias using named anchors in both X5000 and X6000. X5000 driver UUID is
`41C43219-294B-3932-B77E-68824533E800`, version 7.0.25 24657.

The actual PM4 compute table has checkCommandRingSpace at symbol+0x188 and
submitCommandBuffer at symbol+0x198, or object address-point+0x188. This confirms
the two-header-word correction against this machine's Sequoia driver, rather
than only Steve's reference driver. The extracted upstream C++ candidate harness
also passed slot isolation, mismatched-symbol refusal, denied-write handling,
notify ordering and native submit return-value checks on CPU buffers.

Evidence: `build/glfix-guard-20261022/compute-vtable-readonly.json` and
`compute-hook-offline/RESULTS.json`. Our runtime hook remains disabled and the
USB candidate remains unchanged; GPU-reset recovery is still unproven.

## Boot controls and integration boundaries

Current Steve source uses `-NRedDisplayFix`, `-NRedVideoFix`, and `NRedECFix=1/2`.
On Darwin 23/24, DisplayFix enables SubmitGuard and LegacyBlend; on Darwin 25 it also
enables ImmediateSync/SrdShared/ComputeScratch. Without DisplayFix those user display
fixes are off. This differs from our independently enabled, default-on SubmitGuard
and opt-in `-NRedGLFix` / video modes. Its older metal-rendering document still shows
obsolete individual flags; `docs/boot-arguments.md` and actual init methods take precedence.
These new flags are not implemented in our current candidate and should not be added
to our EFI as though they were compatible aliases.

Steve has no equivalent `UserPatches.cpp` OpenGL page-patching module. Keep our
NotificationCenter regression, exact GL vnode checks, GLFixOff precedence, existing
video modes, per-build VCN profiles and DisplayPort/ATOM guards when adapting code.
Shared-cache patches need one coordinated owner per target; installing both competing
Metal implementations could create mixed page contents or conflicting trampolines.

## Concrete migration sequence

1. Finish the isolated NotificationCenter candidate: boot guarded DEBUG UUID
   `9284C47E-E031-3D75-B7B3-E7464414EE20`, verify intact Apple application pages,
   successful GL driver patches and idle NotificationCenter. Keep that baseline backup.
2. Adapt SubmitGuard rollback, full trampoline verification, allocation lifetime and
   its CPU safety tests into a separate change. Preserve the existing payload and
   boot-argument behavior; test injected partial-write and protection failures.
3. Replace the macOS 14/15 Metal blend treatment with exact-profile, gate-only COW
   transactions and their CPU gate/store regression. Ensure the older Metal paths
   cannot apply a conflicting policy. Verify WindowServerApplied and desktop behavior
   after reboot before enabling video acceleration.
4. Investigate the guarded compute vtable correction separately against the recorded
   mediaanalysisd/VTMTSComputeFunction failure. Match before/after workloads and retain
   reset reports; no claim that this candidate fixes our resets is justified yet.
5. Evaluate VCN transaction handling and source-pitch logic with independently verified
   Sequoia functions. Require software-versus-hardware decoded pixel comparisons for
   both H.264 and HEVC, then sustained playback/encode and sleep/wake testing.
6. Keep Tahoe dynamic/scratch work and laptop EC support as separate, version- and
   hardware-specific follow-ups. Preserve existing arguments or add documented aliases
   deliberately rather than silently replacing the user's controls.

Suggested source slices: `128b980` for legacy profiles, installer rollback and tests;
`d1a55d4` / `ea04613` for safety history; `1983f32` for pitch/encode verification;
`08126d3` / `be1545a` for render/vtable work; `338fff9` for the shared resolver.
These commits have dependencies and should be adapted by component, not blindly
cherry-picked over our combined architecture. `dda9f70` is the laptop EC change.

## Checks executed during review

Eight selected upstream CPU/read-only suites passed locally:

- SubmitGuard: 11 tests, including preserving used command contents and neighboring streams.
- LegacyBlend: 16,384 native Sonoma/Sequoia gate/store cases, reproducing 6,144 original condition defects.
- Multi-OS profiles: version/device selection, full pages, tampering and failed reads.
- Generated legacy compatibility data: reproducibility check passed.
- Sanitized actual legacy bridge/installers: write failures, page protection, rollback and idempotency.
- Sanitized compute dynamic bridge: 95 cases, including relocation and eight-page rollback.
- Sanitized video dynamic bridge: 188 cases, including relocation and cross-page rollback.
- Real Mach protection query parity on readable/writable/inaccessible and unmapped addresses.

Logs and structured results are under `build/fork-audit/test-evidence/`; source comparison
facts are in `build/fork-audit/source-findings.json`. No upstream GPU render/encode
probe was run. The upstream fork itself was not built or booted; these checks do not
establish display correctness, speed gains or sustained GPU stability on this machine.

Primary references:
[multi-OS scope](https://github.com/steve12311/NootedRed/blob/128b98067387e0ee49692d424b8543de5739bd6a/docs/macos-multi-os-compat.md),
[runtime transactions](https://github.com/steve12311/NootedRed/blob/128b98067387e0ee49692d424b8543de5739bd6a/NootedRed/UserSurfaceSync.cpp),
[boot controls](https://github.com/steve12311/NootedRed/blob/128b98067387e0ee49692d424b8543de5739bd6a/docs/boot-arguments.md),
[encode change](https://github.com/steve12311/NootedRed/commit/1983f326ebedda9e5596ee6e8ba47af52420ec11).
