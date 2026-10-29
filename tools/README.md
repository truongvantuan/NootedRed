# tools/ — offscreen OpenGL blending probe (NootedRed #158)

`gl_blend_probe` is a small, self-contained CGL/OpenGL 4.1-core harness used to
investigate **NootedRed issue #158**: Chromium/Electron hardware acceleration
corruption and GPU resets caused by the user-space `AMDRadeonX5000GLDriver`
using Vega dGPU values on an AMD iGPU.

It renders into an FBO, reads the pixels back and compares them with a CPU
reference. It never edits files, never injects code, never opens a window and
never takes over the display. **It is still a GPU test on a machine whose GPU is
currently misbehaving — read the safety section before running it.**

Related local documents: `analysis/repro-plan.md` (full evidence + repro plan),
`Chromium-OpenGL-Issue-Report.md` (prior analysis, repository root).

## Files

| File | Purpose |
| --- | --- |
| `gl_blend_probe.c` | the probe (inspect / link / render modes) |
| `build.sh` | compiles it to `build/tools/gl_blend_probe` with `xcrun clang` |
| `README.md` | this document |

## Safety (read first)

Verified on the target machine (macOS 15.8.1, Renoir `0x1638`, NootedRed 0.9.0
loaded), 2026-10-18:

- a minimal CGL/FBO program **SIGSEGV'd on its first `glClear()`** in
  `AMDRadeonX5000GLDriver` at
  `glrAMD_GFX9_UpdateHwExportBlockState ← glrAMD_GFX9_UpdateDrawBufferInfo ←
  glrATI_Hwl_DrawableChanged ← glrBindContextDrawFramebuffer ←
  gldUpdateDrawFramebuffer ← gleUpdateDrawFramebufferState ← glClear_Exec`
  (`~/Library/Logs/DiagnosticReports/glblend2-2026-10-18-211253.ips`,
  and `glblend4-2026-10-18-211622.ips` with the identical stack);
- around the same time the system logged **12+ WindowServer / Electron GPU
  resets** in `/Library/Logs/DiagnosticReports/Kernel_*.gpuRestart`
  (AMD Radeon RX Renoir Graphics, `DID=0x1638`, restart channel 13/23 GFX).

The earlier crashes occurred in the driver's framebuffer update path; their
precise cause was not established. The initial probe's proposed PBuffer setup
was invalid with a core profile and was rejected before rendering. The probe
now draws only into a complete texture-backed FBO, following Apple's
[offscreen rendering guidance](https://developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/OpenGL-MacProgGuide/opengl_offscreen/opengl_offscreen.html).
This fixes the test setup; it does not establish driver correctness.

Rules:

1. `--inspect` (default) is the only mode allowed without Lead approval:
   CGL context + `glGetString` only. It has been run here without a new
   GPU-reset report being logged.
2. `--link` compiles and links shaders but submits no draw calls. It was run
   here without a new reset, but it does exercise the driver's compiler/state
   path; treat it as low-risk, not zero-risk.
3. `--render` refuses to start unless `--yes` is passed. Do not pass `--yes`
   without the Lead's explicit approval, a fresh reboot and a recovery plan.
4. On any GPU reset (new `*.gpuRestart` file), a display corruption event, a
   freeze, or a watchdog/SIGSEGV message: **stop**. Do not immediately retry.
   Reboot to a known-good state before continuing.

## Build

```sh
./tools/build.sh
```

Requirements: Xcode command line tools (`xcrun clang`, SDK with
`OpenGL.framework`), no Homebrew packages. The build does not touch the GPU.
`build/` is git-ignored.

## Usage

```sh
build/tools/gl_blend_probe --inspect            # safe: context + GL strings/extensions
build/tools/gl_blend_probe --exts               # inspect + full extension list
build/tools/gl_blend_probe --link               # + compile/link shaders, no draw calls
build/tools/gl_blend_probe --render --yes       # RISKY: FBO clear/draw/readback + CPU compare
build/tools/gl_blend_probe --render --yes --timeout 30
```

Exit codes: `0` success/all PASS (or only SKIPs), `1` no CGL pixel format/context,
`2` shader compile/link failure, `3` FBO incomplete, `10` rendered pixel mismatch,
`12` render refused
without `--yes`, `124` watchdog, `128+N` killed by signal N.

## Tests and expected values

Blue `(0,0,1,1)` is the FBO clear colour; a full-screen triangle is drawn.

| Case | Blend state | Fragment output | Expected pixel (RGBA8) |
| --- | --- | --- | --- |
| solid, no blend | blending off | `(1,0,0,1)` | `(255,0,0,255)` |
| classic alpha | `SRC_ALPHA / 1-SRC_ALPHA` | `(1,0,0,0.5)` | `(128,0,128,128)` |
| dual-source `SRC1_COLOR` | `SRC1_COLOR / 1-SRC1_COLOR` | `c0=(1,0,0,1)`, `c1=(0.25,0.5,0.75,1)` | `(64,0,64,255)` |
| dual-source `SRC1_ALPHA` | `SRC1_ALPHA / 1-SRC1_ALPHA` | `c0=(0.5,0.25,0.75,1)`, `c1=(0.25,0.5,0.75,0.5)` | `(64,32,223,255)` |

Every pixel in the 64×64 FBO is compared with tolerance ±2 per channel; the test
stops on the first failed case. Alpha uses separate ONE/ZERO factors. The dual-source cases are skipped when the driver
does not advertise `GL_ARB/EXT_blend_func_extended` or reports
`GL_MAX_DUAL_SOURCE_DRAW_BUFFERS == 0`.

A **dual-source mismatch** on the target machine is a strong repro signal: a
driver that silently ignores the index-1 output blends with `c0.a` instead
(for the `SRC1_ALPHA` case that yields `(128,64,191)` instead of `(64,32,223)`).

## Baseline on the target machine (2026-10-18, inspect + link only)

```
GL_VENDOR   = ATI Technologies Inc.
GL_RENDERER = AMD Radeon RX Renoir Graphics OpenGL Engine
GL_VERSION  = 4.1 ATI-7.0.25
GLSL        = 4.10
GL_ARB_blend_func_extended = present
GL_EXT_blend_func_extended = MISSING
GL_MAX_DRAW_BUFFERS = 8, GL_MAX_DUAL_SOURCE_DRAW_BUFFERS = 1, GL_MAX_COLOR_ATTACHMENTS = 8
extension count = 46
c1 bound to frag data index 1: yes
dual-source shaded linked: SRC1_COLOR ok, SRC1_ALPHA ok
```

Notes:

- `GL_ARB_blend_func_extended` present but `GL_EXT_blend_func_extended` missing
  independently reproduces the GLEW observation recorded in issue #158
  (2023-12-10 comment): the ARB entry points exist, the EXT alias does not.
- 46 extensions is tiny for a GL 4.1 driver; GLEngine filters what the AMD
  driver reports.
- **A PASS does not exonerate the driver.** This probe submits a simple
  single-draw sequence; Chromium reaches the same driver through ANGLE
  (`libGLESv2`/`libEGL`) with a very different pipeline/command pattern.
  A FAIL (crash, reset, or pixel mismatch) is much more informative than a PASS.

## What this harness does not do

- It does not run Chromium/ANGLE; use a real Electron/Chromium app for that
  (see the local `analysis/repro-plan.md` §4.8 for the app-level ladder).
- It does not patch or validate any candidate fix. Patch validation is
  approval-gated and should start with the user-space interposer described in
  local `analysis/repro-plan.md` §4.7.
- It does not read or write system files, kexts or the dyld shared cache.

## Recovery notes

If a run hangs, the shell may stay blocked inside the GL driver. Use another
terminal (or ssh) to kill it; if the display is corrupted, force-restart
WindowServer by logging out, or reboot with the power button as a last resort.
The GPU-reset reports in `/Library/Logs/DiagnosticReports` are the first thing to
collect after an incident (`*.gpuRestart`, `gl_blend_probe*.ips`).

## Release feature verification

`sh tools/build-feature-probes.sh` builds the native `video_probe` and `metal_probe` without submitting
GPU work. `video_probe --software-selftest` and `--software-selftest-hevc` generate/decode three 720p
frames using explicitly software sessions. Hardware decode/encode modes require hardware selection
and pixel readback; they cannot count a software fallback as a hardware pass. `metal_probe --render`
checks offscreen opaque/alpha/dual-source pixels; `--compute` checks 64 results. Both snapshot their own
shared-cache patch bytes read-only. These are functional probes, not benchmarks.

`video_probe --encode-h264 --source-pool` uses VideoToolbox's compression-session
source pool for a controlled comparison with the default `CVPixelBufferCreate` path.
Both validate CPU input readback and report strides, IOSurface backing, timestamps
and per-plane output statistics. The diagnostic option does not repair the driver.
On the verified Sequoia cache the probe also snapshots all nine actual VA pages,
including the source-pitch candidate; the verifier requires complete page matches
before hardware video work. These observations are from the probe's own mappings.

`test_vcn_encode_pitch.py` executes the captured Sequoia encoder function with the
production replacement on CPU-only fake objects. It reproduces width/stride mismatches
and checks callback arguments and untouched fields under ASan/UBSan.
`gen_vcn_encode_pitch.py --check` additionally verifies the pinned live cache/image,
complete native function and full page against the cache's embedded CodeDirectory.
Generation refuses an already modified or unsupported source page.

`python3 tools/verify_weachy_features.py` is a read-only evidence collector by default.

OpenCore file-log attribution uses the embedded boot.efi INIT time interpreted
as UTC, with an explicit timing-inference label. `OpenCore_injection_failures`
is `null` when the retained file cannot be associated with the current boot's
timing window; it does not mean there were no failures. The separate
`retained_OpenCore_log_injection_failures` field preserves that file's findings.
FAT mtime or "latest file" alone cannot attribute a recovery EFI failure to the
currently loaded drivers.
`--exercise-metal`, `--exercise-video` and `--exercise-gl` explicitly submit bounded workloads;
GPU exercises require the corrected SubmitGuard v2 boot and stop after a reset, GPU/WindowServer report, signal or timeout; each workload has a delayed-report observation period.
`--deployment <DEPLOYMENT.json>` additionally requires the staged UUID and exact probe hashes.
The GL page check registers the file's existing embedded signature with the kernel before reading
its executable mappings. It does not call GL or run the driver's initializers; an unregistered plain
mapping can otherwise give a misleading stock-page result before normal loader validation.
It saves patch bytes, functional outputs and reset observations as separate evidence.
It also saves `pmset` sleep counters, transition logs and power assertions. Only a
paired sleep/full-wake transition within the current kernel boot plus a positive
sleep counter counts as a recorded system cycle. Dark wakes, display off/on and
previous boots cannot establish it; desktop/device function after wake remains a
separate physical check.
GPU/watchdog report attribution prefers embedded dates over copy-sensitive file
modification times. Timezone-less dates are labeled as local-time inferences;
fresh reports with unresolved dates still block exercises. A retained kernel hang
message also blocks further work even if no reset-begin event has appeared.
`tools/vda_hwtest.sh` now uses this strict native verifier rather than accepting ffmpeg log mentions
or a decodable but incorrect encode as success. See [the feature matrix](../docs/Weachy-Feature-Verification.md).

## Native GPU mapping diagnostic

`-NRedVMTrace` is an optional diagnostic for the guarded 24H32 X5000 driver, not a rendering
optimization. It logs native address assignment and page-table commit/update results for the
OpenGL probe and Zen GPU Helper without changing arguments or results. `test_gpu_vm_trace.py`
executes the production forwarding hooks and installer guards on host fixtures without GPU access.
`verify_weachy_features.py --require-vm-trace` requires all guarded routes before an explicit exercise.
Version 2 additionally observes native mapping address/size/offset/flags and PTE constructor outputs
with thread IDs. Require it with `--require-vm-trace-version 2` (five routes, mask 31).
Constructor outputs are templates, not a readback of installed or GPU-visible page tables.

For an explicitly prepared diagnostic, `--exercise-gl --trace-gl-api --deployment <manifest>`
can observe the GL probe's IOKit calls and mapped command buffers. It requires the observer library's
path and SHA256 in the deployment's `gl_api_trace` entry. The environment is set only for the GL
probe; other collector commands and normal applications do not receive the library. Missing or changed
libraries block GPU work. The capture records whether the library actually loaded. Observing calls and
copying buffers can change timing, so compare its fault address and submission with an unobserved run.
This optional observer is built separately for the investigation; it is not part of the kext.

`decode_gl_api_trace.py <buffers-PID.bin> --gpu <address> --length <bytes> --pid <PID>`
reads a supplied IB extent from the saved snapshots without executing any driver code. Obtain the
address and extent from independent evidence from the same process/test; do not guess them from
an opcode search. It walks type 2/3 packet boundaries from the supplied start and rejects unsupported
types, truncated packets, invalid capture headers and out-of-bounds extents. WRITE_DATA-looking words
inside another packet's payload are ignored. Register/GDS destinations are not reported as GPU memory
addresses. A complete decode covers only the supplied extent, not necessarily the entire IB, and proves
neither execution nor fault causation. Repeated snapshots retain their source record and sequence.
`test_gl_api_decode.py` exercises these rejection cases without GPU access.

`test_gl_budget.py` executes the production zero-budget initializer replacement and the captured
native resource-add routine with CPU stubs on x86_64. The stock 512 MiB input yields a zero list
budget and rejects 4 KiB; the correction supplies a 256 MiB limit only for a zero computed budget.
Other native nonzero results and list limits are preserved. Non-x86_64 hosts report a skip for this
native instruction fixture. The full signed 24H32 GL page is required at runtime; no fallback is
enabled for this function replacement. See [the diagnosis and acceptance checks](../docs/GL-Zero-Budget.md).
See `docs/Weachy-Feature-Verification.md` for the current deployment and coverage limits.
# Conditional OpenGL source checks

The page-local migration keeps the existing `-NRedGLFix` controls. These commands
generate/check reference data and run CPU-only checks; they do not submit GPU work:

```sh
python3 tools/build_opengl_patch.py --check
python3 tools/test_opengl_native.py
python3 tools/test_opengl_dynamic.py
python3 tools/test_opengl_owner.py
python3 tools/test_gl_validation.py
```

The dynamic test accepts an explicit stock reference with `--driver PATH --darwin 24`;
it does not assume the current host is Tahoe or require another mounted OS.
`CXX='clang++ -fsanitize=address,undefined -fno-omit-frame-pointer'` enables
sanitizers for the owner/combined-wrapper tests. The dynamic resolver test already
uses sanitizers. See [the migration report](../docs/OpenGL-Migration-20261025.md).

### Weachy v1.1.1 merge checks

`test_vcn_drain.py` executes the production idle-polling function with a simulated engine,
including deadline, retry, missing-symbol and opt-out cases. `test_hevc_main10_policy.py`
executes the production capability mutator and checks preservation of Main/encode profiles,
missing dictionaries, allocation failure and failed writes. Neither submits GPU work.
`test_user_cache_patches.py`, `test_gl_page_guard.py` and `test_vcn_multibuild.py` additionally
cover independent controls, Gate 0 collisions, and the separated Ventura fixtures.
See [migration report](../docs/Weachy-v1.1.1-Migration-20261026.md) for exact accepted and deferred changes.
# Zalo HEVC startup guard

`zalo_hevc_guard.py` inspects Zalo/Electron 22.3.9 without launching it by default.
`--launch` uses the app-local `PlatformHEVCDecoderSupport` feature disable and
refuses to reuse an unguarded running instance. It changes no EFI setting or app
bundle. `--run --yes` is a coordinated diagnostic launch requiring authenticated
kernel-ring capture; it is not a guarantee against unrelated GPU failures.

`test_zalo_hevc_guard.py` checks inspection-only behavior, app/runtime identity,
feature matching and existing-instance safety without running Zalo or GPU work.
See [the investigation](../docs/Zalo-Freeze-20261026.md) for evidence, measured
results and the HEVC playback limitation.

## Shared-region latency diagnostic

`shared_region_latency.c` measures `shared_region_check_np` including installed
kext hooks in its own process. It submits no GPU work. The syscall may run the
normal private-cache patch handlers; use it only on the selected diagnostic boot.
The first sample is after dyld startup, so it does not measure cold application
launch, cold boot, native-only latency or GPU throughput.

```sh
xcrun clang -std=c11 -O2 -Wall -Wextra -Werror -Wno-deprecated-declarations \
  tools/shared_region_latency.c -o build/tools/shared_region_latency
build/tools/shared_region_latency 16
```

Samples must be 1–256; default is 16. JSON reports the first sample, minimum,
nearest-rank percentiles and maximum in milliseconds. Compare the same machine,
boot profile and loaded kext identity, retaining boot identity with the output.
