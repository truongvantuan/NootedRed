# Riot/graphics hang investigation on Sequoia 15.8.2

27 October 2026. Machine: HP EliteDesk, Renoir 0x1636, 1.5 GiB UMA.
Running OS: 15.8.2 (24H232). Running kext at investigation time: NootedRed
RELEASE UUID `C6B65316-A326-3F6C-A3D6-79611B43677D`.

## What the reports establish

The user identifies `/Users/Shared/Riot Games/Riot Client.app` as the app that
causes UI hangs and tearing. The 16 saved GPU reports from 16:30:56–17:02:58
all record 24H232 and graphics/GFX resets. Their pending command-buffer records
contain 13 Riot Client Helper Metal entries, two Riot entries with an unknown
context label, and two WindowServer entries (some reports contain two pending
records). These entries locate pending work; they do not identify the precise
instruction that caused the hang.

The captured unified log has 92 `GPURestartBegin` lines across those earlier
boots. These are log occurrences, not 92 independently diagnosed root causes.
Three WindowServer watchdog stackshots show GPU-busy display surfaces and an
unresponsive display. At least two earlier boot UUIDs occur in those reports.
This explains how an app GPU fault can stall the whole desktop.

All three VCN queues have zero submitted/completed counters in the GPU reports.
The reported failure is GFX/Metal, distinct from the previously investigated
Zalo startup VCN decode failure. There is no basis here to blame the UMA size,
Wi-Fi root patches, USB mapping or audio configuration.

The current 18:13:28 boot UUID is `B6B2839C-1560-4D97-A2FD-955C7EFD0896`.
No GPU reset was observed on it in this capture. Earlier verification reported
that current boot correctly; it did not inspect the earlier post-upgrade boots
that contain the Riot failures.

## What changed in Apple components

Collected driver identities changed:

| Component | 15.8.1 | 15.8.2 |
| --- | --- | --- |
| AMD GL version | 7.0.25 | 7.0.26 |
| GL UUID | BAD9208B-B99B-3DAA-AA51-15D199498873 | 19CCE60F-8EF6-3AA7-90B9-63AA54AD1584 |
| Metal image UUID | 2F00BC70-A192-30B3-B62D-0039B8A8FCF3 | 6E81115C-F38C-32E2-ADB2-24F44BB32B8A |
| Shared-cache UUID | 42EC2890-BC40-317E-BB27-45142BFF7F26 | 90DB0DEB-2344-3601-B011-B87312D74CFB |

X5000/X6000 kernel identities changed too; the current driver uses a byte-guarded
kernel-family fallback rather than an exact new-build identity.

OpenGL was not removed on this machine. A minimal accelerated NSOpenGLView
query on the running build returned:

- renderer: AMD Radeon RX Renoir Graphics OpenGL Engine;
- OpenGL version: `4.1 ATI-7.0.26`;
- drawable present: 1;
- framebuffer status: `0x8CD5` (complete);
- GL error: 0.

The query opened a small temporary window and submitted no GL drawing commands.
It verifies drawable attachment, not rendered pixels, blend correctness, video
or prolonged stability. Three standalone GL patch pages also matched in the
preceding passive capture.

There was a separately reported NSOpenGLView regression on 15.8.2 release
candidates 24H219/24H225. The original reporter says it was fixed in RC3 24H230.
Apple DTS acknowledged the feedback but did not publish a technical diagnosis.
Our drawable query passes on 24H232; that specific symptom was not reproduced.
Source: [Apple Developer Forums, FB25133383](https://developer.apple.com/forums/thread/850550).

## Concrete NootedRed compatibility defect

`UserSharedCacheData::matches()` recognizes the old Sequoia cache UUID only.
The new UUID is rejected before per-process LegacyBlend and SubmitGuard are
installed. Enabled flags therefore coexist with absent applied markers and
`NRedSubmitGuardRejected=1`.

The actual 24H232 Metal control page remains at `0x7ffb087b3000`, with the same
gate at page offset `0x164`. Its complete 4096-byte reference differs from the
old one at exactly one other byte: offset `0x92C`, `D0 -> C8`. Accepting only the
new UUID would not fix LegacyBlend's independent full-page comparison.

The submit-method address is still `0x7ffb087c3580`, and its 15-byte entry
prologue is unchanged. The collected 47-byte Objective-C wrapper differs at two
bytes in RIP-relative selector references. These observations support preparing
a candidate that retains the existing SubmitGuard payload, but do not prove its
buffer-layout assumptions or hardware behavior on this build.

The loss of these Metal protections is a plausible contributor to the observed
Riot Metal hangs. An A/B boot and reproduction are required before claiming
causation or a fix. GPU ring snapshots alone do not prove stale-tail execution.

## Candidate prepared and staged for the next boot

RELEASE kext:
`build/branches/24H232-metal-candidate/macosx/x86_64/release/NootedRed.kext`

- UUID: `382D20A6-DBBB-3E0E-8282-CDCE0420B1BF`.
- Executable SHA-256:
  `95edb6fbe597f5aef124fcc5379a4d44d75c4bc8e75bb004ad0900815e152dce`.
- Recognizes the exact new shared-cache UUID for existing guarded Metal controls.
- Accepts exactly the two known complete Sequoia control pages, preserving the
  changed non-patch byte and writing only the original two-byte gate.
- Retains other OS profiles, unknown-UUID rejection, page checks, RX payload
  sealing and rollback checks.
- Adds regression coverage for the new variant, idempotency, wrong-byte and
  unknown-UUID rejection. The passive verifier recognizes the new reference.
- Does not change EFI, boot arguments, VCN kernel behavior or VA/GVA tables.

Passed: production cache patch planner/installer tests, native Mach payload
permission checks, feature-verifier negative tests, patch dispatch, semantic
reference data, hook-installation combinations, RELEASE build and ZIP integrity.
These are host checks, not hardware validation. Existing local source work is
preserved; the baseline source files and this task's diff are saved in the study.

## What remains unverified

VA/GVA user-space video patches still require 24H232 data; media readiness
properties do not verify hardware decode/encode. Do not run the full video suite
against the old reference or bypass the guards. The intermittent older Zalo
HEVC startup issue remains separate and unresolved.

Candidate boot procedure: back up the current internal EFI, replace only
NootedRed with the candidate, validate config/manifest, then reboot manually.
First collect passive bytes and confirm the candidate UUID and both
WindowServer-applied markers. Then run one bounded Metal-render test under
capture, followed by compute only if it passes. Reproduce the original Riot
launch last, with work saved and continuous evidence capture, stopping at the
first reset. A failure must not automatically trigger further workloads.

Sleep/wake testing remains deferred until the user is ready. No Riot app launch, GPU render/compute/video workload or reboot was performed
by this investigation. The candidate was subsequently staged with user approval,
as recorded below. The only live OpenGL probe queried context/drawable state.

## Evidence

`build/upgrade-hangs-24H232-20261027/` contains:

- copied reports and parsed GPU/WindowServer timelines;
- unified kernel/WindowServer log and reset excerpts;
- OpenGL drawable probe source, executable and result;
- full-page/method comparison evidence;
- candidate manifest, source baseline, diff, build/test logs.

The local dataset includes private system/app details and Apple binaries. Keep
it local; it is not an upload or public diagnostic package.

## Approved deployment

The user approved staging the candidate. The complete active EFI was copied to
`/Users/tvtuan/EFI-Backups/INTERNAL-before-24H232-metal-candidate-20261027-183446`
and verified against all 123 baseline hashes. Only the candidate NootedRed
kext files changed; config.plist and boot arguments are unchanged. The staged
kext was hash-verified, OpenCore validation passed, and the ESP was unmounted.
The running driver is still the previous build until a manual reboot.

After reboot, collect passive evidence first:

```bash
bash /Users/tvtuan/Github/NootedRed/build/upgrade-hangs-24H232-20261027/collect-after-boot.sh
```

Do not reopen Riot until the candidate identity and actual private Metal patch
bytes have passed. Hardware validation and Riot reproduction remain pending.

## Candidate boot and graphics results (18:36 boot)

Boot UUID `449201E9-997C-48C3-AFDA-9EA2A33A34EE` loads the expected RELEASE
candidate `382D20A6-DBBB-3E0E-8282-CDCE0420B1BF`. The complete LegacyBlend
page, SubmitGuard entry/payload and RX payload protection all pass direct
byte checks. Both WindowServer-applied markers are now present. A sticky
`NRedSubmitGuardRejected=1` does not cancel those successful per-process checks;
other cache identities may still be rejected.

Functional tests passed with continuous kernel-ring capture:

- Metal opaque, alpha and dual-source rendering: all three pixel readbacks pass,
  maximum channel errors 0, 1 and 1 (tolerance 2).
- Metal compute: all 64 output integers match.
- OpenGL rendering/blending: all four pixel cases match exactly, including
  SRC1_COLOR and SRC1_ALPHA. OpenGL 4.1 ATI-7.0.26 is used.

No GPU reset, hang or new GPU/WindowServer report was observed in these tests.
NotificationCenter's 904 signed pages still match. All three GL reference pages
match too. See `POST-BOOT-VERIFICATION.json` for capture paths.

With explicit user readiness, the original Riot Client was launched under a
120-second capture. The user reports its window and desktop work normally.
The GPU helper has no `--disable-gpu` or HEVC-disable guard flag, and owns AMD
accelerator/command-queue IORegistry clients. Final bounded capture result is
recorded separately after the timer ends. This is not a claim of long-term
stability or verified hardware video support.

The shutdown-stall report stamped 18:36 is from the previous boot's shutdown,
not a new candidate-boot GPU fault. It was converted to text for inspection;
it is not being counted as evidence of a failure in this boot.

### Completed original Riot capture

`riot-test-20261027-184246/SUMMARY.json` records the completed 120-second
original-app test: 95 saved kernel-ring snapshots, no GPU fault, no new
GPU/WindowServer report, no capture errors, and the same boot UUID throughout.
The user confirms Riot and the desktop work normally. Both WindowServer
protections remain applied after the test. This supports the compatibility
fix for this workload; longer sessions, other apps and hardware video remain
separate validation tasks. No GPU-disable flags were added.
