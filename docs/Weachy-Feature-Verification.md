# Weachy v1.0.0 feature verification on this machine

Current result and evidence are consolidated in
[Validated-Release-20261023.md](Validated-Release-20261023.md). The tested RELEASE
profile has been restored after withdrawing the failed OpenCore audit batch;
the fresh restored boot passes all seven native cases and the user confirms normal
desktop, menus, speaker and Wi-Fi. The chronology below preserves earlier stages.

Source: [Weachy's release](https://github.com/weachy/NootedRed/releases/tag/v1.0.0),
revision `3b37dfc6282016608962b2746d7809765ad121f4`. Local combined master is `1e3c77e`
plus the working-tree corrections described below. A release description is a requirement to test,
not evidence that the feature works on every APU.

Target: HP ProDesk 405 G6, Renoir `1002:1636` revision CB, **512 MB reserved VRAM**,
macOS 15.8.1 `24H32`, direct HDMI. The user confirmed SVM is enabled again for the
2026-10-23 06:37 boot. Sonoma/Tahoe and a second GPU cannot be hardware-verified on this boot.

Latest observation: the 17:35 boot loads the source-pitch correction and passes both codecs'
hardware decode/encode checks, GL, Metal rendering/compute and Brave WebGL/video/fullscreen.
macOS records a real sleep/full-wake cycle, and all seven native checks pass afterward.
No GPU reset, hang or new report is observed in these bounded checks. AVC-only mode
also passes all four hardware/fallback cases on the later boot. AVCEncode now
passes all four cases too. The full-feature RELEASE profile has booted and passes
all seven native cases plus browser WebGL/video/fullscreen. Physical RELEASE
resume and post-wake/device checks remain pending.
See [GL-Zero-Budget.md](GL-Zero-Budget.md), [VCN-Encode-Pitch.md](VCN-Encode-Pitch.md) and the final section below.

## Requirements and evidence

| Release feature | Source/configuration and current evidence | Acceptance still required |
| --- | --- | --- |
| Metal translucent UI / LegacyBlend | Corrected capability gate for 14/15; preserve `dualSource || !allowRBPlus`. On the 08:05 repaired boot the full private page matches, opaque/alpha/dual-source pixels pass (maximum error 1; disabled-fix dual-source error 45), and the user reports normal menus. | Broader applications and sustained stability. These combined changes do not isolate each patch's contribution. |
| Metal SubmitGuard | Same upstream 307-byte PM4 tail filler. Complete entry, payload, continuation and RX checks pass on the repaired boot. Bounded Metal rendering and compute pass without new faults during their observation windows. Installer rollback and malformed-entry host checks pass. | Broader submission patterns and stability. Installation markers alone remain insufficient. |
| Shared-region syscall / FairPlay exclusion | Production host tests verify all three syscall arguments and the return/error path. FairPlay entitlement test includes absent/false/true entitlements and release of the copied object. | DRM playback is not promised: release itself lists hardware DRM limitations. No entitlement bypass is introduced. |
| AVC/H.264 hardware decode | Corrected 17:35 boot and real post-wake check: hardware-required sessions; three 720p frames exactly match software decoding. Browser playback/fullscreen also passes. | Broader profiles/resolutions and sustained use are coverage limits, not verified by this bounded test. |
| HEVC hardware decode | Corrected 17:35 boot and real post-wake check: hardware-required sessions; three 720p 8-bit frames exactly match software decoding. | Unsupported profiles and 10-bit remain separate coverage. |
| AVC-only alternative | `-NRedAVC` wins over other video modes. On boot session 40628072, H.264 hardware decode/encode and automatic HEVC software decode/encode all pass, with no observed GPU fault and normal desktop confirmed. Eight production flag-combination tests also pass. | These flags select alternative profiles, not simultaneous features. AVCEncode is verified separately below. |
| Experimental encoding | With the pitch correction, full-VDA H.264 hardware encoding passes (mean error 0.0107, max 1); HEVC passes (mean 0.00927, max 7). Both return three frames validated by software decoding and pass after system sleep/wake. Separate AVCEncode mode also passes hardware H.264/HEVC encoding. | Broader streams/resolutions and sustained use remain coverage limits. |
| VCN GFXOFF suppression | Hold marker is active. Three Brave video start/stop/fullscreen cycles pass, followed by a recorded system sleep/full wake and passing native media/GL/Metal checks. Unready-bridge host regression passes. Suppression includes idle time while the engine remains allocated. | Longer use and measured idle/power behavior. Do not label an always-held engine a measured power optimization. |
| Compute stability | Both integrated upstream tips leave the experimental compute submission vtable overwrite disabled. Native Metal compute passes 64/64 results before and after real system sleep/wake without observed new faults. | Broader compute workloads remain a coverage limit. The disabled overwrite has not been verified or enabled. |
| Two-GPU compatibility | External AMD gating and override exist; non-AMD external GPUs do not block VDA. Host gate tests pass. This PC has one iGPU. | A second suitable machine is needed for a two-GPU hardware claim. Not applicable to this machine's deployment. |
| OpenGL shader-engine / dual-source fixes | All three GL pages match, including the zero-budget correction. Native pixel cases, user-observed Zen WebRender and Brave WebGL 1/2 pass. Native GL also passes after real system sleep/wake; NotificationCenter code remains valid. | Broader workloads and other driver builds remain coverage limits. |
| Signature/semantic fallback | Production fixture tests cover all three OS families, exact/context/semantic/resolver dispatch and rejection of the captured NotificationCenter collision. | Runtime supported-build evidence; a nearby minor-build fallback cannot be proved by tests only on 24H32. |
| Compatibility collector | Ran successfully on 15.8.1; generated `compat/nred-compat-15.8.1`, 131 files. Version detection and output organization work. | Collected page-cache bytes may be patched: do not generate new stock reference tables from this collection without its provenance checks. |

## Corrections made for this audit

Weachy's dynamic LegacyBlend `allow` offsets `0x30354D1DB` and `0x3087B3185` point
inside other instructions. Actual SETcc sites are `0x30354D1E1` and `0x3087B3198`.
The old exact/semantic paths zeroed the RBPlus predicate, while the dynamic path attempted
to force it true. Instead of making these paths fight, Sonoma/Sequoia now open only the
hardware gate and preserve Apple's downstream predicate. Tahoe retains the existing
verified reference gate/allow pair; no Tahoe address is used on Sequoia.

LegacyBlend runs even when SubmitGuard is already installed or its method cannot be patched.
Its full-page check rejects unrelated code. Fixed-offset hooks additionally verify the cache UUID.
SubmitGuard verifies the complete trampoline and continuation, not six generic jump bytes.
Failed entry writes restore the original bytes and RX permissions; an allocated trampoline is
retained if rollback cannot be verified, avoiding a dangling executable jump. Maximum permissions
are not reduced, so a subsequent rollback remains possible.

The rendering corrections now have the bounded runtime results recorded below; the separate
video candidate is **not runtime-verified**. Native probes do not
alter system files or cache bytes; they snapshot their own mappings for read-only verification.
The existing CoreMedia `allowMetalTransferSession=false` workaround remains in place. Removing
that workaround requires a separate media/compute comparison after the bridge is verified.

## Builds and post-boot checks

```sh
python3 tools/test_user_cache_patches.py
sh tools/build-feature-probes.sh
build/tools/video_probe --software-selftest
build/tools/video_probe --software-selftest-hevc
```

The software reference tests passed on this machine (maximum pixel difference 1).
The hardware probes select **Require**, not merely **Enable**, and require an affirmative hardware
property. Missing hardware properties are accepted only for explicitly software sessions, where the
Apple SDK documents a default of false. Hardware tests cannot pass using that default.
Metal checks compare every pixel of 32x32 opaque, ordinary-alpha and dual-source draws; compute
checks 64 integer results. These bounded cases are not performance benchmarks or long-term stability tests.

After the staged rendering-repair boot (video still disabled):

```sh
bash /Users/tvtuan/Github/NootedRed/build/weachy-features-20261023/collect-after-boot.sh
```

The initial collector is read-only: it verifies the deployed UUID/probe hashes, actual GL pages,
private SubmitGuard/LegacyBlend bytes, NotificationCenter CodeDirectory hashes, properties, dmesg
and the latest OpenCore log. It submits no render, compute or video workload. Explicit future
`--exercise-*` runs additionally check delayed GPU/WindowServer reports and stop on a fault.
OpenCore log provenance uses the embedded boot timestamp as a timing inference; file mtime alone is insufficient.
An old Zen support export is rejected. UI appearance and physical sleep/wake still need observation.

Artifacts: `build/weachy-features-20261023/`. `DEPLOYMENT.json` records exact identities and rollback
hashes. A 105-file verified backup is at
`~/EFI-Backups/OPENCORE-before-render-v2-20261023-075245/EFI`.
Staged DEBUG UUID: `09F19F11-8ABE-3A09-9CE1-C46EF03CA23E`.
Staged args: `-v debug=0x100 keepsyms=1 -NRedDebug -NRedGLFix`.
Only the kext executable and boot-args changed. The full VDA/GFXOFF profile is validated as
`full-video-candidate.plist` but is **not installed**. Rollback:
`python3 build/weachy-features-20261023/rollback.py` (hash guarded; `--check` validates only).
The 08:05 physical boot verified rendering patch installation and bounded Metal tests. OpenGL failed,
video remains disabled, and the overall goal is incomplete.

## Freeze during the disabled-fix baseline

The Metal pixel probe finished at 06:53:06; a GPU hang was recorded at 06:53:13.
The report has a VMID 1 TCP read/range fault at `0xc938ad397000`, with pending Metal work from
WindowServer and Ghostty. This differs from the prior Zen CPG write fault at `0x400004000`.
WindowServer watchdog reports follow at 06:56, 06:59 and 07:00. Panic metadata reports no
WindowServer check-in for 120 seconds. The user hard-rebooted; current boot started at 07:46:54.
The diagnostic is a likely trigger by timing, but the exact offending command is not proven.
The IORegistry query stalled later and cannot explain the first GPU hang. The repaired kext was
not running during the incident. See `FREEZE-ANALYSIS.json` and the preserved reports.

No more GPU workloads were run on that baseline boot after the user's freeze report. The collector uses a shallow
text IORegistry query and bounded child-process termination. Runtime testing must first establish
the corrected build and actual patch installation. A probe's completed command or nonzero pixel
result is not proof that the display remains healthy afterward.


## Separate video candidate

The VCN GFXOFF failure-path correction is built separately under
`build/branches/video-gfxoff-guard/`. It is not installed on the USB. The already-staged rendering
repair UUID and boot profile remain unchanged. `test_vcn_gfxoff.py` reproduces the old failure
and executes the corrected production hooks across active, unready, failed and missing-resource
states. `test_feature_verification.py` rejects foreign cache identities, corrupt payloads, wrong
continuations, RWX trampoline mappings and missing evidence. The verifier now refuses GPU tests
unless actual patch bytes match and the current boot has no recorded GPU/WindowServer fault.

## 08:05 rendering-repair boot

Boot epoch 1792717544 loads DEBUG UUID 09F19F11-8ABE-3A09-9CE1-C46EF03CA23E.
The initial 08:07 read-only observation saw stock GL pages; a later CPU-only signed-page validation
and follow-up capture found both full intended patched pages and NRedGLFixGLApplied=1. This is
consistent with delayed application; it does not establish a failed installation from the initial read.
LegacyBlend full-page bytes, SubmitGuard entry/payload/continuation and RX protection match.
NotificationCenter's 904 code pages match; CPU usage is 0.0%. No GPU restart or watchdog report
is recorded through the read-only capture. The corrected capture now records successful dmesg status.

The user reports a responsive desktop with normal menus. A bounded Metal render test then passes
all opaque, source-alpha and dual-source cases, with maximum channel error 1 versus the disabled-fix
baseline's dual-source error 45. The delayed GPU/WindowServer checks find no new fault.
Evidence: metal-render-verified-boot/SUMMARY.json. These combined rendering corrections work for this
bounded case; it does not isolate the individual contribution of LegacyBlend versus SubmitGuard.
Subsequent compute and OpenGL results are recorded below. VDA and physical sleep/wake remain
unverified for this build.

The newest OpenCore log embeds boot.efi INIT 2026-10-23T01:05:18. Interpreting it as UTC puts it
26 seconds before this kernel boot: it is consistent with the current boot despite a file timestamp
seven hours earlier. That association is a timing inference. It also records an AppleALC injection
Invalid Parameter error, and AppleALC is not in the loaded-kext list. That separate audio finding has
not been changed or attributed to NootedRed.

The separate native Metal compute test now passes 64/64 integer results, with verified cache
patch bytes and zero new GPU/WindowServer fault reports. Evidence:
`metal-compute-verified-boot/SUMMARY.json`. This verifies the small compute workload while the
experimental compute vtable overwrite remains disabled; it does not verify every compute workload.

## OpenGL failure on the repaired boot

`GL-render-verified-boot/SUMMARY.json` verifies both intended GL pages and the Metal cache patches,
but the first 64x64 solid-color test reads `(0,0,0,0)` instead of `(255,0,0,255)` and exits 10.
The driver reports a GPU hang; the kernel records GPURestartBegin at 08:18:09.456.
The pending GL buffer belongs to probe PID 1508, VMID 11, GPU address `0x400060000`.
The command-processor history contains WRITE_DATA opcode `0xc0033700`. This identifies the
probe's stalled GL submission; it does not identify an offending address or the cause of the hang.
The user confirms the desktop remains responsive. Further GPU work stopped, and video is still disabled.

The initial post-test dmesg capture failed because sudo lost its terminal timestamp; the command
runner now preserves the terminal session for sudo. A subsequent successful capture contains 424
allocation-failure lines, but the initial fault has already left the ring. Raw unified-log JSON also
contains truncated messages; it does not recover the missing fault address. Allocation-failure
counts alone cannot establish that 512 MB reserved VRAM caused this failure.

Offline parsing of the earlier Zen command image now walks 198 type-3/type-2 packet boundaries
from offset zero to the first zero word at `0x1280`. The write at `0xe54` is on an actual packet
boundary. Its destination is `0x400004000`, and its control selects a confirmed, incrementing
memory-sync write. The next packets perform event/release/wait operations on that resource.
These field meanings come from AMD's [packet definitions](https://github.com/GPUOpen-Drivers/pal/blob/dev/src/core/hw/gfxip/gfx9/chip/gfx9_plus_merged_f32_me_pm4_packets.h)
and [opcode definitions](https://github.com/GPUOpen-Drivers/pal/blob/dev/src/core/hw/gfxip/gfx9/chip/gfx9_plus_merged_pm4_it_opcodes.h).
This strengthens the blit-resource synchronization lead without proving a mapping, residency,
permission, firmware or GPU-state defect. No speculative kernel mapping patch has been installed.

Future explicitly requested exercises now require a successful initial kernel-ring read and sample
the ring every 0.5 seconds through the bounded probe and delayed report window. Changed snapshots
are retained with hashes and timestamps, capped at 192 snapshots and 1 MiB per snapshot.
Capture failures stop subsequent tests. CPU-only regression fixtures verify that a transient fault
survives a later ring overwrite and that missing privilege prevents submission. This improves
evidence collection; it does not fix OpenGL or authorize repeating the failed workload this boot.

## Next-boot native mapping diagnostic

An opt-in `-NRedVMTrace` diagnostic now observes the native X5000 memory-map address assignment,
commit and update methods. The installer requires Darwin 24, driver UUID
`41C43219-294B-3932-B77E-68824533E800`, all three named symbols, in-image bounds and each method's
exact 32-byte prefix before routing any method. A rejected or partial installation is reported in
`NRedVMTraceRejected` / `NRedVMTraceRoutes`; the collector requires all three routes.

The hooks forward every argument and return value unchanged. They only read the address and raw
option fields identified in this driver build. Logging is limited to `gl_blend_probe` and
`Zen GPU Helper`, the initial `0x400000000..0x4000fffff` address range, and 1,024 operations.
Begin/end records have matching event numbers. No field is reinterpreted as a proven PTE permission,
and a successful commit will not by itself prove that memory was resident when the GPU used it.
Operations performed by a kernel worker outside these process names will not be recorded.

Production-hook host tests with ASan/UBSan verify guard rejection, argument/result forwarding,
unchanged object bytes, process/address filtering, event limits and partial-route reporting.
The prefixes independently match the installed kernel collection. DEBUG and RELEASE builds and
ZIP checks pass. The DEBUG build emits the pre-existing `processKext` stack-frame warning;
both the current and diagnostic binaries allocate the same `0x740` bytes in that function.
This is recorded rather than treated as a new trace-hook regression.

The diagnostic DEBUG UUID `ECCC0FF0-89FC-3964-847E-2DE15EF3B19C` is staged for the next USB boot,
with `-NRedVMTrace` added to the existing rendering profile. Video remains off. The full 104-file
EFI backup is verified at `~/EFI-Backups/OPENCORE-before-GL-VM-trace-20261023-084050/EFI`.
Only the NootedRed executable and boot-args changed; ocvalidate passes. Rollback inputs are verified.
The running kernel is still the earlier rendering repair, so these hooks are not runtime-verified.

After reboot, run the read-only collector:

```sh
bash /Users/tvtuan/Github/NootedRed/build/gl-vm-trace-20261023/collect-after-boot.sh
```

Its manifest, build identities, backup hashes, rollback script and native disassembly are under
`build/gl-vm-trace-20261023/`. A separate GL exercise is prepared but has not been run. It requires
the expected kext, verified rendering patch bytes, all trace hooks and a boot without recorded GPU
faults. The full release-feature goal remains incomplete pending an OpenGL fix and video verification.

## 08:45 diagnostic boot and complete fault capture

Boot epoch `1792719936` loads the expected diagnostic UUID, with `NRedVMTraceEnabled=1` and
all three route bits (`NRedVMTraceRoutes=7`). The initial collector saw stock GL pages while the
private Metal patches already matched. Merely mapping and executing an existing RET, with either
an unsigned or hardened ad-hoc-signed CPU-only helper, did not change that observation.

Registering the GL driver's existing embedded signature using `F_ADDFILESIGS_RETURN` then made
both full intended GL pages visible before GPU work. This is the existing-file signing operation
documented in Apple's [fcntl header](https://github.com/apple/darwin-xnu/blob/main/bsd/sys/fcntl.h),
without a replacement signature or driver initialization. The collector now does this preparation
before its page comparisons. The initial stock results therefore did not prove a missing patch.
Bounds and malformed Mach-O signature-command regression fixtures pass.
`boot-20261023-085523-1313/SUMMARY.json` verifies exact GL pages, complete private Metal patches,
the diagnostic hooks, zero resets and NotificationCenter's 904 valid code pages before the exercise.

One bounded GL exercise then fails its first solid-color draw, reads zero pixels and exits 10.
The collector preserves 34 ring snapshots, including a complete fault block:

- Probe PID 1362, SubmitContext GL, VMID 9, pending IB `0x400060000`.
- GPU page address `0x400001000`, access WR, client 6 (CPG), labels VALID and WRITE.
- Six native commit calls return true, including `0x400004000`; the trace does not contain a commit
  starting at `0x400001000`. Sizes and PTE bytes were not recorded, so a containing mapping is possible.
- No assign/update events are retained, despite all three hooks being installed. Their presence
  cannot establish that those specific methods handled every allocation.
- One restart-begin event; NotificationCenter code remains valid; the user confirms the desktop is responsive.

This fault address differs from the earlier Zen fault at `0x400004000` (which also had a NACK label).
Do not equate their exact mechanisms or interpret a successful native commit as successful GPU access.
GPU work stopped after this failure; video is still disabled. Evidence:
`GL-test-20261023-085559-1343/`, `GL-FAULT-ANALYSIS.json`, `CHROMIUM-GUIDE-AUDIT.json`.

The user's referenced Chromium usage guide is archived at `docs/archive/Chromium-Fix-Usage.md`.
Its required GLFix flag, exact patches, Lilu ordering and exclusion of conflicting graphics patchers
are verified here. Its reported hardware validation is for `0x1638`; this machine is `0x1636`.
The current-path [usage note](Chromium-Fix-Usage.md) records that distinction and the remaining failure.


## 12:06 diagnostic v2 boot

Boot epoch `1792732003` loads our DEBUG UUID `B4D2EC51-AD47-3C3B-9132-4BDF0D899529`.
The initial capture at `build/gl-vm-trace-v2-20261023/boot-20261023-120742-945` verifies both full GL
pages, the private Metal page and complete SubmitGuard trampoline, all 904 NotificationCenter code
pages, and VM trace version 2 / routes 31. It submits no GPU work and finds zero resets.

One subsequent bounded GL test, `GL-test-20261023-120812-1064`, fails on the first solid-color draw
with zero RGBA and exit 10. It records one new GPU reset, probe PID 1088 / VMID 7, and a CPG write
fault at `0x400001000` (VALID, WRITE). The pending IB is `0x400060000`, consumed size `0x4a0`.
The user confirms that the desktop remains responsive. Further GPU work on this boot stopped.

All six native commits and mapping-range calls return true. Their observed intervals are:

| Start | Size | End, exclusive |
| --- | --- | --- |
| `0x400020000` | `0x20000` | `0x400040000` |
| `0x400040000` | `0x20000` | `0x400060000` |
| `0x400004000` | `0x4000` | `0x400008000` |
| `0x400080000` | `0x80000` | `0x400100000` |
| `0x400060000` | `0x20000` | `0x400080000` |
| `0x400014000` | `0x4000` | `0x400018000` |

None contains the faulting page. This does not prove it was never mapped: initialization, worker
threads and other paths outside these hooks/process filters remain unobserved. All 141 captured
constructor outputs include valid/read/write bits. The physical argument is zero because the native
`mapVMPTE` path constructs a template and supplies the physical base separately to its update routine.
These are neither mappings to physical address zero nor proof of GPU-visible permissions. The raw
option `0x10` is therefore insufficient evidence for a read-only resource diagnosis.

The final ring snapshot begins in the middle of constructor event 27, losing its timestamp but
retaining the same fields. The parser now preserves an intact duplicate's timestamp rather than
calling this a conflicting result. `VM-mapping-details-reparsed.json` retains the corrected derivation;
raw snapshots and original summary remain unchanged. The CPU regression covers both observation
orders and still rejects genuine field/timestamp differences.

No allocation-failure line is retained during this run. VRAM exhaustion is not established as the
cause. The last processed opcode includes WRITE_DATA, but its IB payload/destination is not in this
capture. Root cause and attribution to upstream/local/Apple code remain unresolved.

The next prepared capture is `build/gl-vm-trace-v2-20261023/run-gl-api-test.sh`, after a clean reboot
and initial capture. It adds a hash-verified observer only to `gl_blend_probe`, alongside the existing
kernel ring capture. It reads allocation responses and bounded shared command-buffer snapshots;
no application profile, kext, EFI, GPU command or mapping is changed by the observer. Its copying/logging
can affect timing. It has been compiled but not run on this build. Video remains off. The ordinary GL
script should not be repeated on the already faulted boot.


Before the next GPU run, CPU validation found and repaired a defect in the private API observer:
its snapshot fallback could request 4096 bytes after allocating a smaller buffer. AddressSanitizer
reproduces the old heap overflow using the actual snapshot loop with CPU-only fake mappings; the
corrected loop only retries smaller sizes and passes its capture-limit cases. The rebuilt observer's
hash is recorded in DEPLOYMENT.json. It was not loaded during the 12:08 GL test, so this helper defect
cannot explain that fault. No additional GPU work or EFI change was made for this correction.

The strict offline decoder reproduces the old Zen command evidence in seven identical snapshots:
a 198-packet supplied prefix contains WRITE_DATA at 0xe54 targeting 0x400004000. An earlier snapshot
of that mapping has an incomplete stream and is rejected. This validates the decoder against the old
capture; it does not establish the current probe's command destination. Source and limits are recorded
in OBSERVER-VALIDATION.json. Actual GPU observation with the corrected helper still requires the next
clean boot and prepared capture.


## 12:26 command capture and staged zero-budget correction

The observer loaded in probe PID 1027 and saved 4,458,624 bytes of snapshots. The first GL draw
still fails with one reset, CPG write fault 0x400001000 / VMID 10. The allocator returned that exact
address with 4096 resident bytes. Six identical IB snapshots decode a 219-packet prefix with
WRITE_DATA at byte 0xc24 targeting the same resource. The ring's size field 0x4a0 is in dwords
(0x1280 bytes), not bytes. The user confirms a responsive desktop; no further GPU work ran on this boot.

The 512 MiB device-info value propagates to the GL resource-list calculation `(MiB << 10) - 0x80000`
KiB, yielding zero. The native addition routine cannot fit the 4 KiB resource against this budget.
CPU execution of the actual native instructions reproduces the rejection and verifies a correction
that supplies 256 MiB only for a zero computed budget. The original nonzero results are preserved.
This is an inherited Apple GL calculation that the Weachy feature patches do not change. Runtime
causation and a rendering fix still require the candidate boot comparison.

Both DEBUG and RELEASE candidates build and ZIP-verify under `build/branches/gl-zero-budget/`.
All 16 host checks pass. The DEBUG candidate, UUID `D687C8DC-274B-3E38-AF70-0D798EF38460`, is staged
on the OPENCORE USB. Only the kext executable changed; boot arguments and video-off mode are preserved.
A full verified 104-file backup is at `~/EFI-Backups/OPENCORE-before-GL-zero-budget-20261023-125850/EFI`.
Rollback inputs and the saved config pass the read-only rollback check. No reboot was performed by the agent.

Initial next-boot collection:

```sh
bash /Users/tvtuan/Github/NootedRed/build/gl-zero-budget-20261023/collect-after-boot.sh
```

The verifier now checks all three complete GL pages, including 0x5000. The new function page is
exact-only and still requires the GL executable vnode identity. No nearby-build fallback is allowed
for it. Once the clean baseline and loaded UUID/bytes are verified, `run-gl-api-test.sh` in the same
directory performs the bounded GL comparison. Correct pixels, resource mappings and delayed stability
must be checked before a hardware pass. Metal regression checks, Zen, video and sleep/wake remain pending.
Full evidence and source details: [GL-Zero-Budget.md](GL-Zero-Budget.md).

## 13:08 boot: GL correction passes; next step is video

Our DEBUG UUID `D687C8DC-274B-3E38-AF70-0D798EF38460` is loaded, with all three complete
GL pages and the private Metal patches verified. The previous zero-budget resource
now has a successful native 4096-byte mapping at `0x400001000`. Four native GL pixel
cases pass both with and without the process-local observer. Metal rendering passes
three cases and compute returns 64/64 correct results. These tests record no new GPU
reset or GPU/WindowServer report; NotificationCenter's 904 code pages remain valid.

Zen's normal profile starts with `MOZ_DISABLE_RDD_SANDBOX=1`, without the observer.
The user reports Compositing **WebRender**, and supervised startup records no GPU
fault. A fresh support-text export is still absent. Brave/Chromium 156, in a temporary
profile, passes WebGL 1/2 clear and triangle readbacks with exact pixels and AMD Renoir
ANGLE Metal renderers in both contexts. The private result validator's missing
`webgl2` status-key assumption was corrected offline; its original result is retained.
Browser WebGPU/media feature labels are not treated as functional tests.

The user selected Apple menu → Sleep and reported normal operation afterward, but
`pmset` reports Sleep Count 0 and no matching current-boot system-sleep transition.
Full system sleep/wake remains unverified. Caffeine has a display-idle assertion;
this alone does not prove it blocked an explicit sleep request.

Evidence: `build/gl-zero-budget-20261023/RUNTIME-PASS.json`. DEBUG has this runtime
evidence; RELEASE is built and ZIP-verified but has not been boot-tested. All 16
host checks passed before deployment.

The running boot still has video disabled. Only the USB configuration has subsequently
changed: it adds `-NRedVDA -NRedVCNNoGfxOff` for the next boot and retains the same
working DEBUG binary. A verified 104-file backup of the working video-off EFI is at
`~/EFI-Backups/OPENCORE-before-full-VCN-20261023-132942/EFI`. The saved config passes
ocvalidate, and the config-only rollback input check passes.

After rebooting from the OPENCORE USB, collect a baseline first:

```sh
bash /Users/tvtuan/Github/NootedRed/build/vcn-full-20261023/collect-after-boot.sh
```

The collector verifies the loaded identity, actual patch bytes and VCN readiness before
any video exercise. The separate `run-video-test.sh` performs hardware-required decode
and encode checks with independent pixel validation, stopping on failure. It has not
been run on this video-off boot. Full video, its GFXOFF hold, alternative AVC boot modes
and physical system sleep remain open requirements. Earlier next-boot instructions
above are historical; use this profile for the next capture.

## 14:01 full-VDA boot and encoding candidate

Both hardware-required decoders pass three 720p frames with exact software-reference
pixels. H.264 hardware encoding returns corrupted pixels; an IOSurface-backed
session-pool comparison fails identically despite correct CPU input readback.
No GPU reset/report is observed; the user confirms normal desktop/menus. HEVC
encoding is not submitted after the failure. All eight existing VA patch pages
are verified in the probe's actual mappings, including feedback-stride patches.

The native source-pitch calculation ignores the texture's stored byte stride.
An exact-only Sequoia correction now passes 45 native CPU cases and the production
page/bridge guards. All 17 host checks and both build/ZIP checks pass. The DEBUG
candidate UUID `A501FFE9-7952-3A7A-83A7-19BBDA54E22C` is staged; it has no runtime
encoding proof. Only the NootedRed executable changed. Three externally added
sensor/TSC kext entries are preserved and recorded as additional next-boot changes.

Use the new read-only collector after reboot from OPENCORE USB:

```sh
bash /Users/tvtuan/Github/NootedRed/build/vcn-encode-pitch-20261023/collect-after-boot.sh
```

The collector now requires all nine actual VA pages before video submission;
markers alone cannot verify the candidate. Root evidence, guards, backup and
comparison limits are described in [VCN-Encode-Pitch.md](VCN-Encode-Pitch.md).
This supersedes the preceding next-boot profile. Full goal completion remains
unproven pending encoding, broader media use, alternative modes and system sleep.

The subsequent 14:41 boot still loads D687 with all three added kexts active. Its
bounded pre-pitch H.264 comparison reproduces mean error 75.5203 / maximum 192,
with zero resets or new reports. The added kexts alone have therefore not resolved
encoding. Current-boot evidence is under `vcn-encode-pitch-20261023/pre-pitch-boot-144155/`
and `h264-pre-pitch-20261023-172828/`. Historical reports had newer file mtimes;
embedded-date provenance now prevents counting those copies as new boot faults.

## 17:35 corrected boot: full profile and resume pass

DEBUG UUID `A501FFE9-7952-3A7A-83A7-19BBDA54E22C` loads with the full recommended
video profile. All three GL pages, nine VA pages and private Metal patches match.
Native hardware H.264/HEVC decode each matches three software-reference frames
exactly. H.264 encoding now has mean pixel error 0.010725 / maximum 1; HEVC has
mean 0.009268 / maximum 7. All four hardware cases pass. GL pixel cases, Metal
opaque/alpha/dual-source rendering and 64-element compute also pass.

Brave/Chromium 156 reports AMD Renoir ANGLE Metal and passes WebGL 1/2 readback.
Three generated-video playback/start/stop/fullscreen cycles pass, observing 464
video frames and VideoToolboxVideoDecoder in all players. Those browser properties
are distinct from the native probes' strict hardware-required session proof.

The OS records sleep 17:49:19, dark wake 17:49:44 and full wake 17:49:52. All three
counters equal 1, and the user confirms normal desktop/menus. Seven post-wake
native checks (Metal render/compute, both codecs' decode/encode and GL) pass.
No GPU reset/hang/new report is observed; NotificationCenter code pages remain
valid. A later four-second wall-clock correction changes `kern.boottime` without
a new boot session. Follow-up collectors now record the stable boot-session UUID.

Evidence: `build/vcn-encode-pitch-20261023/RUNTIME-PASS.json`, the video/native/browser
captures linked there, and `post-wake-test-20261023-175410-2175/SUMMARY.json`.
This is bounded single-machine evidence, not a sustained-use or all-OS guarantee.
Alternative AVC/AVCEncode controls remain to be boot-verified. The requested EFI
production audit follows that verification; the subsequent AppleALC repair is
documented in [EFI-Production-Readiness.md](EFI-Production-Readiness.md).

## AVC-only runtime verification and repaired speaker

Boot session `40628072-8F3E-4A2E-BBC5-E5F27D694DDB` loads the same A501 DEBUG kext
with `-NRedAVC`, AVCOnly=1 and HEVCEncodeAllowed=0. All actual GL/VA/private Metal
patch checks pass. H.264 hardware decode returns exact software-reference pixels;
hardware encode has mean error 0.010725 / maximum 1. HEVC automatic decode and
encode select software while hardware remains allowed by the probe, and both pass
pixel validation. No GPU reset/hang/new report is observed, and the user confirms
a responsive desktop with normal menus. Evidence:
`build/vcn-avc-mode-20261023/RUNTIME-PASS.json` and its linked four-case capture.

AppleALC now loads, Internal Speakers is the default output, and the user confirms
sound works. This separate repair restored damaged relocation bytes from the
earliest EFI backup; no audio layout-ID change was necessary. Bluetooth is
deferred at the user's request. The subsequent AVCEncode and RELEASE staging
results are recorded below.

## AVCEncode runtime pass and production RELEASE staging

Boot session `B1ADFABA-5D0D-4F00-8F1F-0DF9D28B7889` loads A501 DEBUG with
`-NRedAVCEncode`, AVCOnly=1 and HEVCEncodeAllowed=1. H.264 hardware decode/encode,
automatic HEVC software decode, and HEVC hardware encode all pass, with the same
bounded pixel errors as the full-VDA tests. Actual patch-byte checks pass, and
there are no observed GPU hangs/resets/new reports or OpenCore injection failures.
The user confirms normal desktop/menus. AppleALC and Internal Speakers still
enumerate. Evidence: `build/vcn-avc-encode-mode-20261023/RUNTIME-PASS.json`.

All three video-mode controls now have runtime evidence. RELEASE UUID
`4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B` and the full recommended GL/VDA/GFXOFF
profile are staged for the next USB boot. Diagnostic flags and OpenCore file
logging are disabled; compatibility/security settings are preserved. The exact
backup, config/binary hashes, guarded two-file rollback and next-boot checks are
in `build/production-release-20261023/`. RELEASE runtime and physical resume
were unverified at staging time. The subsequent RELEASE results follow.

## RELEASE native and browser verification

Boot session `444C8425-65B1-4872-BA31-13F678743155` loads RELEASE UUID
`4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B`, with full GL/VDA/GFXOFF flags and no
diagnostic boot flags. The actual full GL, VA, LegacyBlend and SubmitGuard patch
checks pass, and VCN is ready. All seven native cases pass: Metal rendering,
compute, hardware H.264/HEVC decode and encode, and GL rendering. NotificationCenter
code remains valid. A temporary Brave profile then passes hardware WebGL 1/2
pixels and three video/start/stop/fullscreen cycles, observing 485 frames through
VideoToolboxVideoDecoder. The temporary browser instance is closed afterward.
No GPU reset/hang/new report is observed in either supervised suite.

Evidence: `build/production-release-20261023/RUNTIME-PASS.json` and its linked
native/browser summaries. These results establish bounded RELEASE functionality;
physical RELEASE system sleep/wake, post-wake rendering/media and device checks
remain pending. OpenCore file logging is disabled for this profile, so historical
OpenCore files are not current-boot injection proof.
