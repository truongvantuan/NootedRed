# Validated RELEASE setup, 23 October 2026

24 October update: the [post-install audit](Postinstall-Audit-20261024.md) verifies
an ACPI-only repair on OPENCORE, with all seven native cases passing before and
after a real system sleep/wake and normal devices/automatic Wi-Fi rejoin confirmed. The
110-file profile and functional results below describe the tested rollback
baseline; RELEASE graphics/media binaries remain unchanged.

The OPENCORE USB is back on the tested RELEASE profile. All 110 recorded files
match, including OpenCore and our corrected NootedRed. A fresh boot after the
failed audit passes all seven native checks, with no observed GPU hang/reset/new
report. The user confirms normal desktop/menus, PC-speaker sound and Wi-Fi.

| Component | Current identity |
| --- | --- |
| Hardware/OS | HP board 872E, Renoir 1002:1636, 512 MiB reserved VRAM; macOS 15.8.1/24H32 |
| OpenCore | RELEASE 1.0.9, source 6d8490d, logging off |
| NootedRed | Our RELEASE 1.0.0, UUID 4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B |
| NootedRed binary SHA256 | 0d0d56e05284cfa6b73b712f7f60763f4f1358568d5b88eae2c1ccb3ae13a85e |
| Config SHA256 | 0138e51b6b4e0655790e1fac98b52e4144b2bcd24ecce066cbf8aeb7dee366cf |
| Boot arguments | keepsyms=1 -NRedGLFix -NRedVCNNoGfxOff -NRedVDA |

## Feature evidence

| Weachy release feature | Verification on this deployment |
| --- | --- |
| Metal LegacyBlend/translucent UI | Complete patch bytes and opaque/alpha/dual-source pixel cases pass; normal menus confirmed. |
| SubmitGuard | Complete entry/payload/continuation and RX checks pass; native render/compute succeeds. Production installer/rollback/failure fixtures pass. |
| Syscall ABI/FairPlay exclusion | Production host tests verify forwarding/error paths and entitlement handling. Hardware DRM support is not claimed. |
| Full VDA | H264 and HEVC sessions require hardware; three 720p 8-bit decoded frames exactly match software references. Both codecs' hardware encoding passes independent software readback. |
| AVC-only profile | Separate boot passes H264 hardware decode/encode and automatic HEVC software decode/encode. The probes allow hardware and verify the actual selection. |
| AVCEncode profile | Separate boot passes H264 hardware decode/encode, automatic HEVC software decode and HEVC hardware encode. |
| VCN GFXOFF suppression | Hold is active; video start/stop/fullscreen and a recorded physical system sleep/wake pass. This hold includes idle time while the engine is allocated; no measured power saving is claimed. |
| Compute stability | 64/64 native results pass. The inherited experimental compute-vtable overwrite remains disabled, as in the integrated upstream tips. |
| GL/Chromium acceleration | All three GL pages and four native pixel cases pass. Brave uses AMD ANGLE Metal for WebGL 1/2, with correct pixel readbacks and three video/fullscreen cycles. Zen WebRender was separately observed earlier. |
| Dynamic compatibility resolver | Enabled with GLFix; host fixtures cover exact/context/signature/semantic dispatch and collision rejection across reference OS families. This OS uses verified exact profiles; other minor builds are not runtime-certified. |
| Dual-GPU compatibility | Production gate/override host tests pass. This PC has one iGPU, so no two-GPU hardware result is claimed. |
| Compatibility collector | Automatic version detection generated the collection at build/weachy-features-20261023/compat/nred-compat-15.8.1; 133 evidence files are present at final verification. Captured patched mappings and legacy pattern candidates must not be treated as stock golden patch data. |

The RELEASE profile passed all seven native cases before and after a recorded
system sleep/wake. The user confirmed normal desktop, menus and sound, plus
automatic Wi-Fi reconnection; an interface-bound connectivity check passed.
Brave observed 485 video frames over three start/stop/fullscreen cycles. The
restored boot then passed the same seven native cases again. These are bounded
functional checks, not a benchmark or a guarantee for every stream/application.

## Corrections and EFI review

The implemented corrections include the NotificationCenter GL-pattern collision
guard, corrected Metal blend semantics/private-cache transactions, the zero GL
resource-list budget at 512 MiB, the unready-VCN GFXOFF guard and the VCN encoder's
actual texture-stride handling. Both DEBUG and RELEASE archives are validated.
Source integration contains Weachy's v1.0.0 commit; the subsequent fixes remain
local working-tree changes on master, not published commits.

All config sections were reviewed against live devices and
`/Users/tvtuan/Downloads/SysReport`. Native PCI0 UID and gfxutil confirm root 1
despite the report's root-zero strings. ALC897 receives requested layout 11;
AppleALC's reported AppleHDA layout 7 is separate. The damaged AppleALC executable
was restored and PC-speaker playback is confirmed. The source of that corruption
is unknown. CPU patches encode 8 cores/16 threads, one PAT variant applies, USB
maps match live controllers, and kext references/dependency order pass.

## Withdrawn audit and remaining limits

The later OpenCore DEBUG/logging switch and EC/APFS refinements were deployed
together and caused a reported pre-macOS boot hang. That entire audit batch was
withdrawn. The repair used the current tested RELEASE files and verified package,
not the old EFI used for recovery. Boot after restoration is now verified. The
individual trigger within the failed batch is **not proven**; it must not be
presented as an identified NootedRed defect or as a safely reapplicable change.

Captured audit attempts show MAT support, successful OpenRuntime rendezvous and
APFS acceptance. Their CPU-frequency warning takes a successful fallback path;
Watchdog status 0 is a setting, not a failure code. Static validation was not
sufficient to establish bootability. Failed EFI/logs are preserved for a separate
controlled investigation if needed. No further speculative EFI tweaks are staged.

Bluetooth is deferred by request. Other OS versions, a second GPU, unsupported
HEVC/10-bit profiles, hardware DRM and long-duration stability are outside the
hardware evidence above. Wi-Fi auto-rejoin is confirmed for the observed cycle,
not as a proven permanent cure for an intermittent earlier issue. Existing custom
SIP/authenticated-root and SecureBootModel settings are preserved; this is a
functionally validated setup, not a claim of security hardening or measured peak
performance. The CoreMedia workaround remains in place. No internal-disk EFI was
installed and no source changes were pushed.

## Evidence and recovery

- Current restored boot: `build/config-full-review-20261023/RESTORED-RUNTIME-PASS.json`.
- Full RELEASE/browser/resume: `build/production-release-20261023/RUNTIME-PASS.json`.
- Alternate profiles: `build/vcn-avc-mode-20261023/RUNTIME-PASS.json` and `build/vcn-avc-encode-mode-20261023/RUNTIME-PASS.json`.
- Failed audit and repair: `build/config-full-review-20261023/FAILURE-ANALYSIS.json` and `RELEASE-CORRECTION.json`.
- Archives/checksums: `build/production-release-20261023/ARTIFACT-VALIDATION.json`.
- Exact current files: `build/production-release-20261023/FINAL-EFI-manifest.json`.
- Complete pre-audit tested EFI backup: `/Users/tvtuan/EFI-Backups/OPENCORE-before-config-full-audit-20261023-230847/EFI`.

The read-only collector remains available at
`build/config-full-review-20261023/collect-after-boot.sh`. The withdrawn refinement
restore action is disabled; do not reapply the failed audit batch.
