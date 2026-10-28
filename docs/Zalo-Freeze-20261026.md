# Zalo startup freeze — 26 October 2026

The 17:30 incident was a VCN0Dec hardware-video hang during Zalo startup. Its
GPU helper blocked while releasing a VideoToolbox HEVC session. WindowServer
then became unresponsive and the watchdog recorded a panic. The user confirmed
that no chat/video had been opened and that a force restart was needed.

An app-local startup guard has been tested successfully. It prevents Zalo's
Chromium HEVC capability probes. It does **not** repair the underlying AMD HEVC
driver or establish that all media workloads are stable.

## Evidence and incident provenance

Evidence is retained locally in `build/zalo-freeze-20261026/`; it is not committed.
The failure boot is `01AD0604-2851-4C13-9810-F77CCB3E8005`. Queries constrained by
wall-clock time also returned another boot, so analysis uses the matching boot
UUID. Copied report mtimes are not used as proof of event time.

- At 17:30:29, decoder service PID 69113 was starting alongside Zalo PID 69110
  and Zalo GPU helper PID 69111.
- At 17:30:40, channel 12 / VCN0Dec timed out with two pending stamps.
- At 17:30:41, the kernel declared the channel hung and began GPU recovery.
- The scoped log contains 16 `GPURestartBegin` events; seven GPU-reset report
  files were retained. All seven identify decoder PID 69113 as first pending
  video work. Report-file count and recovery-event count are different measures.
- The first decoded WindowServer stackshot covers 17:31:06–17:31:11 and reports
  40 seconds without a successful check-in. Its output was decoded offline;
  this did not run an application workload.
- The saved `.contents.panic` records the 17:33 watchdog panic with 120 seconds
  without a WindowServer check-in. The separately named full panic file was not
  available; the retained wrapper contains the panic text.

The GPU reports show 1.5 GiB VRAM. Their VM-fault snapshot is a read at virtual
address `0x400100000`, VMID 8, while the pending video context uses VMID 9. This
does not prove which instruction/packet caused the hang, and the address is not
a physical VRAM requirement. An out-of-memory diagnosis is not established.

The evidence identifies the graphics/media failure path; it does not implicate
the Wi-Fi driver. No fork-specific causal attribution has been established.

## What blocked

The GPU helper's `CrGpuMain` thread is waiting in
`VTDecompressionSessionInvalidate` and synchronous XPC. The decoder service is
inside:

```
AppleGVAHEVCDecoder
AvdVAContext::DeleteContext
VAVcnDecoder::Terminate
VcnEngine::deleteVcnContext
IOConnectCallMethod
AMDRadeonX6000 / AMDRadeonX5000 / IOAcceleratorFamily2
```

Other WindowServer/kernel waiters are blocked behind that service thread. This
is stronger evidence than Zalo merely being open at the same time as a reset.

The installed kernel collection has the same X5000/X6000 UUIDs as the incident
stackshot. Symbol resolution maps X6000 offset `0x49584` to
`AMDNavi10VideoContext::removeContext` + `0x16a`; X5000 frames include
`AMDAccelChannel::waitForTimestamp` and `resetHardwareAndReplay`.
The local mapping is saved in `KERNEL-STACK-MAP.json`. Our bridge explicitly
drains VCN on client/accelerator stop; that alone does not establish that each
video-context removal is protected. Since these stacks were sampled after the
channel hung, they cannot establish whether context removal caused the initial
failure or subsequently waited on it. No speculative kernel hook was installed.

## Why this can happen before a chat or video

Zalo 26.10.20 (build 26.10.20.3253) bundles Electron 22.3.9. Its actual x86-64
framework UUID matches the incident image. Read-only Mach-O unwind analysis maps
the blocked Electron return offset `0x245e0c1` to the cleanup in the function at
`0x245dab0`.

That function was identified by matching all six complete H.264/HEVC probe
parameter sets and its call structure to Chromium's
[`InitializeVideoToolboxInternal`](https://github.com/chromium/chromium/blob/108.0.5359.215/media/gpu/mac/vt_video_decode_accelerator_mac.cc).
The compiled feature check is also present at `0x245dcdf`.

The startup routine creates and releases decoder sessions to preload native
libraries before sandboxing. Its HEVC probes use **Main, 8-bit, 4:2:0**, at
1280×720 and 320×240. The SPS fields were parsed independently from the exact
matched bytes. No user video frame is needed to enter this lifecycle path.
The probe labeled "software" still permits hardware: its helper always sets
EnableHardware=true and varies only RequireHardware. This makes session
creation/teardown a relevant test distinct from decoding and waiting for frames.

This is not evidence for enabling `-NRedHEVC10`: the identified probes are
8-bit, and that boot argument cannot repair their failure. The earlier App
Store incident shares the VCN/HEVC failure class but had a different workload.
The exact failing GPU packet and deeper driver lifetime/synchronization defect
remain unresolved.

## Tested application workaround

The guarded command is:

```sh
/Applications/Zalo.app/Contents/MacOS/Zalo --disable-features=PlatformHEVCDecoderSupport
```

This feature gates the matched HEVC startup block. The guard does not add
`--disable-gpu` or disable all accelerated video decoding. Other acceleration
controls remain at their existing values; actual H.264 playback/backend and
video-call behavior were not tested in this session.

The 60-second guarded test recorded:

- A live Zalo browser, GPU helper and renderer processes.
- The HEVC-disable feature forwarded to every observed GPU helper, including
  after Zalo appended its own feature list.
- Zero GPU failure events before/after, no capture errors and 98 kernel-ring
  snapshots.
- User confirmation that the chat list loaded and the desktop remained normal.

The existing Zalo bundle passed strict signature verification. EFI and the
original Zalo bundle were not changed by the guarded-launch workaround. A later
diagnostic driver installation is recorded below separately.

## Use the launcher

A self-contained, locally signed **Zalo HEVC Guard.app** is installed in
`~/Applications`, with a shortcut of that name on the Desktop. Use that launcher
for subsequent starts. The original Zalo/Dock/login startup entry does not gain
the command-line guard automatically. No Dock or login-item preferences were
changed.

The launcher reuses an already guarded instance. It refuses to reuse an
unguarded instance, which must be quit first. Unknown Electron versions are
refused pending review. Seven host-only launch-policy tests pass. The installed
launcher was checked and exercised by activating the running guarded instance.

The tradeoff is that Zalo's platform HEVC video support is disabled. HEVC-specific
playback may consequently be unavailable; software fallback is not promised.
Other applications retain their existing media settings. This is a targeted
workaround for the identified startup trigger, not an all-format driver fix.

## Tools

### Driver repair investigation

The guard is temporary containment. A successful guarded start does not close
the underlying HEVC defect. Earlier playback probes submitted frames and
explicitly invalidated sessions before release. Chromium's startup probes
submit no frames and release their session references directly. Consequently,
passing playback did not test the same lifecycle that blocked during startup.

`tools/vt_lifecycle_probe.mm` now isolates the two HEVC configurations and
reports progress around session creation, optional explicit invalidation and
release. Its default mode only constructs format descriptions. An explicit
software control forbids hardware; the explicit hardware mode preserves
Chromium's normal-required/small-permitted hardware selection policy. The
small case is not assumed to select hardware: the actual selection property
is reported separately. The probe submits no compressed frames, although
creating or releasing a hardware decoder can still issue GPU work and hang.

The local `lifecycle/fixtures.json` contains the parameter sets matched against
the installed Electron binary, including PPS values compiled as overlapping
immediate stores. `lifecycle/BUILD-VERIFICATION.json` records compilation,
format-only verification and rejection of four invalid execution-option
combinations. Subsequent hardware results are recorded below.

This is an HEVC subset reproducer, not an exact Electron environment: it omits
the preceding H264/VP9 probes and sandbox/process setup, and its backend
property query adds an API call. A passing run cannot establish a repair or
exclude a sequence-dependent failure. Hardware execution needs coordinated
early kernel capture and saved user work. A process timeout cannot contain a
GPU hang. The initial probe did not install a kernel hook; the later opt-in trace
build does, as described below.

### Hardware lifecycle capture and next diagnostic boot

At 21:38, `lifecycle/capture-20261026-213831-pair` captured both zero-frame
sessions using the installed baseline RELEASE driver. Both reported actual
hardware selection, direct release returned for both, and the collector saved
89 kernel-ring snapshots with zero GPU failure events. The global idle-drain
counter increased from 69 to 73, with maximum waited time remaining zero.
This rules out a deterministic failure of this isolated pair on this boot; it
does not exclude an intermittent or larger-sequence defect.

After the user quit Zalo, a fresh launch requested
`--enable-features=PlatformHEVCDecoderSupport`. Zalo replaced the GPU helper's
enable list with `JXL`, while no HEVC-disable flag was present. The initial
collector stopped early on the forwarding mismatch; this was not a complete
90-second pass. The user confirmed the chat list and desktop were normal.
The installed binary's feature object has default state 1 (enabled), but this
does not prove its effective runtime state: Chromium permits overrides and
field trials ([feature definition and override semantics](https://raw.githubusercontent.com/chromium/chromium/108.0.5359.215/base/feature_list.h)).
Attempts to read only that feature object were denied by macOS process
protection. No app re-signing or security-setting changes were made.

An opt-in **diagnostic RELEASE** build was subsequently built and installed:

- UUID `7752C1BE-7F51-3114-9BF3-7A2A74AE3AB4`.
- Adds `-NRedVCNTrace` and routes the native X6000 video `newContext` and
  `removeContext` methods only on exact build 24H32 after checking both entry
  byte signatures against the locally verified kernel collection.
- Logs begin/end, PID, native status and event ID, bounded to 512 operations.
  It preserves native arguments, return values, waits and session lifetime.
- Host tests verify full-width argument forwarding, output pointers, native
  errors, opt-out behavior and the logging bound. Existing drain, GFXOFF and
  multi-build checks pass. This is instrumentation, **not a driver fix**.
- The full previous EFI is backed up at
  `~/EFI-Backups/INTERNAL-before-zalo-context-trace-20261026-215439/EFI`.
  The active change consists of NootedRed and the additional trace boot argument.
  OpenCore 1.0.9 validation passed before and after installation.

The existing running kernel remains the old UUID until reboot. After reboot,
run `bash build/zalo-freeze-20261026/lifecycle/collect-after-boot.sh` from the
repository. This collector starts no application and checks the loaded UUID,
trace readiness, native trace pairs and GPU events. Continuous capture must be
started before the next deliberate Zalo launch. `lifecycle/restore-previous.py`
restores only the prior kext/config and refuses if those files have subsequently
changed. The exact first bad packet, a corrective driver change and validation
with Zalo HEVC enabled remain outstanding.

### 22:12 boot and captured original-app startup

Boot `3AF3C582-E297-42E7-A397-3D1BC8C2ACAE` loaded the expected context-trace
driver and reported context tracing ready, with zero GPU failure events.
`lifecycle/capture-20261026-221333-pair` repeated the hardware HEVC pair:
both sessions selected hardware and completed release. The native trace
recorded two creates and two removals, all with matching exits/status zero.

`original-startup-20261026-221529` then observed the user opening the original
Zalo for three minutes. It saved 538 kernel snapshots with no capture errors
or GPU failure events. Decoder PID 3818 performed four creates and four removals
(events 9–16), all returning zero. The four earlier probe operations are
baseline evidence, not additional Zalo operations. The user confirmed the chat
list and desktop were normal. The helper had no HEVC-disable flag, but the
effective feature state and codec identity are not proven by trace pairs alone.

The hardware probe ran before Zalo. A first-use/initialization race therefore
remains possible; a post-warm-up pass cannot establish cold-start stability.
The next experiment must launch Zalo directly after capture readiness, without
running the probe first. Instrumentation can also affect timing, so a trace-build
pass is not proof that a production race has been corrected.

The existing optional VM trace had two gaps for this incident: it only selected
the earlier GL clients, and its upper bound excluded exactly `0x400100000`.
VM trace version 3 now accepts the full/truncated native decoder name and
extends the window by one 4 KiB page, to exclusive upper bound `0x400101000`.
Native methods, map arguments, PTE values and return values remain unchanged.
Sanitizer tests cover both decoder names, inclusion of the fault page, exclusion
at the new upper bound, range overflow, native forwarding and logging bounds.
All five method signatures still match the local X5000 kernel collection.

The expanded diagnostic RELEASE build is installed for the next boot:
UUID `C6B65316-A326-3F6C-A3D6-79611B43677D`, with both `-NRedVCNTrace` and
`-NRedVMTrace`. The previous context-only EFI is separately backed up at
`~/EFI-Backups/INTERNAL-before-zalo-vm-trace-20261026-222948/EFI`; the original
production backup remains available. No functional driver repair is claimed.

After quitting Zalo, reboot without reopening applications. Before opening
Zalo, browsers, App Store or Codex, use Terminal to run:

```sh
bash /Users/tvtuan/Github/NootedRed/build/zalo-freeze-20261026/lifecycle/capture-original-after-reboot.sh
```

This checks the pinned driver UUID, context readiness and all five VM trace
routes, starts continuous capture, then opens the original Zalo through
LaunchServices with no feature-disable switch. It runs no warm-up probe.
An already-running Zalo prevents a controlled launch. Kernel snapshots and
metadata are flushed to disk; messenger stdout/content is not collected.
The machine may still freeze; a process deadline cannot contain a kernel hang.

```sh
python3 tools/zalo_hevc_guard.py             # inspect; does not launch
python3 tools/test_zalo_hevc_guard.py        # host-only safety/policy checks
python3 tools/zalo_hevc_guard.py --launch    # ordinary guarded launch; no sudo
```

For an explicitly coordinated diagnostic run, quit Zalo first, save work,
authenticate kernel-log access with `sudo -v`, then use `--run --yes`. The test
can still encounter an unrelated graphics failure. Capturing messenger stdout
is deliberately avoided, and user chat/account data is not needed for this
diagnosis.
