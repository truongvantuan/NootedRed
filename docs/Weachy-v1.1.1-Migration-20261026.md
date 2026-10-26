# Weachy v1.1.1 migration — 26 October 2026

Adapted [Weachy v1.1.1](https://github.com/weachy/NootedRed/releases/tag/v1.1.1),
pinned to `d7f2ec99eb80756602b98e6644d188a271c4e762`, into the local master working tree.
This is our combined build, with deliberate conflict resolutions, rather than an identical upstream binary.
Original HEAD `1e3c77e87d9981afdc0fcf5096d237b1febc075f` and its ancestors are unchanged.
No reset, stash, rewrite, automatic commit or push was performed.

The complete tracked/untracked source snapshot, original worktree patch and file hashes are in
`build/weachy-v1.1.1-migration-20261026/before-source.tar.gz`, `before-working.patch` and
`BEFORE-MANIFEST.json`. Existing IDE files were preserved. Build products and ignored external
platform datasets remain in their existing locations. No pre-migration source file was deleted.

## Upstream changes and conflict choices

| Commit | Change | Combined result |
| --- | --- | --- |
| `f44dd3a` | Resolver isolation and Sequoia offset correction | Retain our exclusive, complete-block OpenGL owner, exact Metal pages and paired semantic planner; reject lone Metal signature fallback. Our existing Sequoia page/predicate already uses the verified gate and preserves the stock allow predicate. |
| `986e69d` | Remove site-only writes; vnode filter | Adopt fail-closed target filtering, including null/unknown names; remove our remaining legacy site/context-only fallback. Our filter accepts exact driver names and the specific x86 cache prefix, rather than arbitrary `dyld` substrings. |
| `efe90c3`, `a39270c`, `d7f2ec9` | Intermediate/final versions | Set final xmake and Xcode module version to 1.1.1; local provenance remains explicit. |
| `269c096` | Ventura GL/Metal, independent blend flags, dynamic blend windows | Import supplied Ventura full-page tables. Keep full-page identity and our rollback writer instead of 384-byte opcode-based sliding search. Add independent flags with explicit disable taking precedence. No duplicate validation hooks. GL-only configurations still install their exclusive hook when disabling Metal leaves zero legacy page records. |
| `454d73a` | Multi-OS generation and diagnostics | Merge VA/GVA profiles and extraction improvements; auto-name collected outputs by actual OS/build while retaining our registered VCNData layout and output isolation. Do not import the relaxed KC receiver-window matcher: its accepted patterns include instructions that do not establish the required RDI receiver. Existing strict KC extraction is retained. |
| `5a94132` | Main10 safety policy and decoder teardown wait | Cap only HEVC decode Profile 2 level to zero unless explicitly overridden. Preserve Main/AVC and encode capability dictionaries. Add optional-symbol idle polling before native client/accelerator stop, with at most 250 ms requested sleep and timeout diagnostics. Actual elapsed time may exceed 250 ms due to scheduling or time inside the native predicate. |
| `be32de0` | Verify restored VM maximum protection | Retain our sealed SubmitGuard allocation: current and maximum RX are both checked. Existing cache pages keep original maximum rights so verified rollback can acquire a private writable copy; blindly reducing their maximum rights would break that recovery path. Current RX restoration, readback, rollback and reachable-payload retention stay tested. |
| `9a427e3`, `c50afe4` | Ventura 22G513 VCN/VA/GVA data | Same feature appears twice in history; integrate once. Port arrays into `VCNData/22G513.hpp` with exact build/Darwin/device gates and all ABI byte guards. Retain all existing exact/family variants. Sonoma GVA table correction is included. |

Our generated Steve OpenGL payloads/relocation planner, 512 MiB zero-budget correction,
VA encode-pitch correction, allocation/VM diagnostics, X5000 and native cache rollback helper
remain byte-for-byte unchanged. `LOCAL-PRESERVATION.json` records eleven critical files.
The VCN bridge retains `-NRedVCNNoGfxOff`, including native fallback on failed bridge activation;
upstream's removal would otherwise silently discard the workaround used by our tested EFI.

The drain uses only the ABI-guarded native idle predicate. If the predicate cannot be resolved,
it does nothing and reports not ready. It does not call an unverified native wait and then claim
success. A timeout is recorded and teardown continues; this is bounded mitigation, not proof
that every teardown race or GPU hang is eliminated. Its default-on behavior still needs hardware validation.

## Ventura data limits found during review

The supplied `UserPatchesVentura.inc` identifies **13.7.8 / 22H730**, while the new VCN/VA/GVA
headers identify **13.6.4 / 22G513**, restricted upstream to Cezanne `0x1638`.
They are kept separate. The kernel bridge accepts only the exact Ventura build, Darwin 22.6,
and device `0x1638`; it does not enable Ventura media on this machine's Renoir `0x1636`.

In the supplied Metal full-page fixture, the gate is at page offset **0x22c** and the allow
predicate at **0x258**. Upstream's private blend nominal offsets instead use **0x24c** and
**0x278**. Our page planner uses the actual gate, verifies the reference opcode and every
other page byte, and leaves the stock allow predicate intact. The corresponding private
cache mapping is additionally pinned to the 22H730 UUID from upstream's generator profile.
Unknown pages/builds remain unchanged.

The Ventura fixed SubmitGuard method address has no supplied complete method-page reference
that resolves the mixed-build provenance. Its constant is retained as upstream metadata but
`getMethodOffset(22)` returns zero. `NRedSubmitGuardSupported=0` / `Enabled=0` report that
limit; full-page LegacyBlend can still run independently. This avoids enabling an unproven
trampoline merely because its short prologue happens to match. Existing Darwin 23–25
SubmitGuard behavior remains available. Ventura hardware behavior has not been tested locally.

## Controls and compatibility

Existing boot arguments are retained:

```
keepsyms=1 -NRedGLFix -NRedVCNNoGfxOff -NRedVDA
```

No EFI change is required to request the new default media safety behavior.

| Control | Behavior |
| --- | --- |
| `-NRedSubmitGuard` / `-NRedNoSubmitGuard` | Submit protection defaults on where supported; explicit disable wins. Turning it off no longer implicitly disables LegacyBlend. |
| `-NRedLegacyBlend` / `-NRedNoLegacyBlend` | Blend protection defaults on. Explicit disable suppresses both private-cache and native/semantic Metal blend paths. |
| `-NRedHEVC10` | Opt out of the new Profile 2 capability cap. Not added to this EFI. |
| `-NRedVCNNoDrain` | Skip teardown polling for diagnosis. Not added to this EFI. |
| `-NRedVCNNoGfxOff` | Preserved independently from draining. |

Advertising a zero Main10 decode level is host-tested. Successful software selection/playback
on this hardware still needs runtime verification. Before installation the running accelerator
advertises level 153 for Main/Profile 1 and Main10/Profile 2; `before-accelerator.plist` preserves
that baseline. The collector records actual per-profile levels after boot, rather than treating
an enable property as proof the capability mutation occurred.

## Build and validation

Both RELEASE and DEBUG were built using the existing AppleForge/xmake workflow, with output
isolated under `build/branches/weachy-v1.1.1-20261026/macosx/x86_64/`. The xmake configuration
is returned to RELEASE. No upstream release binary is substituted for our merged source.

The 27 configured regression commands complete successfully: **26 verified checks and one
explicit framebuffer UUID skip**. The skipped native framebuffer check is not a passed hardware test.
Checks include 1,236,096 CPU OpenGL cases, 295,272 sanitized resolver cases, 293 real writer
cases, 545 real validation-wrapper cases, cache rollback/failure injection, independent flag
combinations, null/unrelated-vnode collisions, exact Ventura data/build selection, bounded drain
cases, 64 production hook-installation control combinations and Main10-only mutation with allocation/set failure. Existing encode-pitch, GFXOFF,
DP and allocation trace checks remain covered. Archive bytes, bundle version and RELEASE
dSYM identity are verified. DEBUG retains the toolchain's normal package layout.

Exact artifact names, UUIDs and SHA256 values are in
`build/weachy-v1.1.1-migration-20261026/ARTIFACTS.json`.
`REGRESSION-FINAL.json`, per-check logs and `MIGRATION-DELTA.json` preserve the review evidence.

## Installation and remaining verification

**Installed and boot-tested on the internal EFI on 26 October; all seven native cases passed.** The full previous EFI is backed up at
`/Users/tvtuan/EFI-Backups/INTERNAL-before-weachy-v1.1.1-20261026-095626/EFI`. Installation changed only the complete NootedRed bundle;
all 111 EFI files were checked and OpenCore 1.0.9 validation passed. Configuration and boot arguments are unchanged.

The following installation guidance is retained for future replacements. Keep the verified backup available.
When choosing to install, replace the entire `NootedRed.kext` bundle with the merged RELEASE
bundle, including its 1.1.1 Info.plist. Do not mix the old plist and new executable. Existing
OpenCore `Kernel/Add` paths and boot arguments remain the same.

After boot, run:

```
bash /Users/tvtuan/Github/NootedRed/build/weachy-v1.1.1-migration-20261026/collect-after-boot.sh
```

This collector checks the expected RELEASE identity and patch bytes, records watchdog/service
state and HEVC capability levels, and submits no GPU exercise or sleep request. It does not
mount or alter EFI. If the ESP is unmounted, EFI log discovery can remain unverified while
runtime identity and patch checks are still collected. Controlled native graphics/video,
media close/reopen, Main10 software playback and real sleep/wake checks follow only after
that boot is healthy.

This update is not claimed to fix the separate 26 October watchdogd startup panic. That
incident's missing IOWatchdog service still requires its own boot-time verification.

## First boot verification (2026-10-26)

The merged RELEASE booted and all seven native graphics/video output cases passed.
Actual Main10 capabilities are capped at level zero while Main remains at 153; the
SubmitGuard payload is current/maximum RX. All 111 installed EFI files match.
The user confirmed normal baseline devices and a responsive desktop after the suite.

Four 250 ms client-stop drain timeouts predated the suite; 31 subsequent drain calls
added no timeout. No GPU reset/hang or new GPU/WindowServer report was observed.
These bounded successes do not close the residual drain-warning investigation,
actual Main10 software playback, long-term stability or real sleep/wake validation.
The earlier watchdog startup failure did not recur during this observation.

Evidence: `build/weachy-v1.1.1-migration-20261026/boot-20261026-101152/FINDINGS.md`
and `VERIFIED-BOOT.json`.

## Later App Store freeze (2026-10-26 11:53)

The full-VDA profile later suffered a decoder-channel reset storm and WindowServer timeout.
Decoded App Store stacks show HEIF image/tile decode through AppleGVAHEVCDecoder;
the responsible decoder PID matches the pending GPU work. Ordinary short video tests
did not cover this workload. Full HEVC decode is therefore not considered production-ready
on this machine. A backed-up config-only change stages `-NRedAVCEncode` instead of
`-NRedVDA`, preserving hardware AVC decode and encoders while requesting HEVC software
fallback. This mitigation requires reboot and actual App Store verification.
Evidence and next-boot collector: `build/freeze-investigation-20261026/FINDINGS.md`.
