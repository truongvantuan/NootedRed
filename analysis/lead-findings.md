# #158 Chromium/GL corruption — Lead investigation state (2026-10-18, pre-reboot)

> **LIVE SYSTEM WARNING**: this investigation triggered a GPU reset loop on the test box
> (18+ `Kernel_*.gpuRestart` between 21:12 and 21:20, WindowServer + DeepSeek Harness killed).
> The user chose to reboot at 21:21. **Do not run any GPU/OpenGL/Metal render test until after a
> clean reboot and desktop stabilization.** The CGL probes and the interposer are still in /tmp.

## Kernel-side leverage verdict (from task-2, static)

- **Kernel CAN supply arg2**: `AMDAccelDevice::getHardwareInfo` (X5000 kext 0x4364dde) memcpys
  0x204 bytes of the kernel `AMDHWInfo` at `AMDHardware+0xd0` to the GL driver via
  `IOConnectCallMethod(selector 0x100)`. NootedRed currently does not hook this, but every field is
  kernel-controlled.
- **Kernel CANNOT fix the actual literals**: `_gfx9_HwInfoInitData` hardcodes family 0x8D and the
  SE/RB/CU presets into the *destination* record; `_amdUbm_HWL_Init` hardcodes 0x8D too; user-space
  AddrLib only accepts 0x8D/0x8F for Gfx9. No kernel field carries "family". So a kernel-only fix
  for #158 is **not possible** — the root fix must be a user-space patch (which is what
  `NootedRed/UserPatches.*` + A1 now does).
- **arg3 is likely a gpus-layer copy of GB_ADDR_CONFIG** (`device+0x2e8` is not written by the GL
  driver; bits 16–18 match `SHADER_ENGINE_TILE_SIZE`). Observed `arg3=0x00010000` on Renoir, i.e.
  bit 16 set. Note: NootedRed's `GoldenSettings.hpp` Renoir GB_ADDR_CONFIG is `0x24000042` (Raven
  value, bits 16–18 = 0), while Linux Renoir uses `0x22010042` (bits 16–18 = 1, among other bit
  differences). This deserves a read-only audit after reboot: log `mmGB_ADDR_CONFIG`/`self+0x48`
  and compare with the Linux Renoir value; if NootedRed writes the Raven value on Renoir, that can
  independently corrupt addrlib tiling (and may explain why the GL driver sees the "dGPU" bits).
  This is a **kernel-side candidate** but was not proven before the reboot and is not part of A1.
- Navi leftover in `X6000FB` is display/FB-side, not the 3D/blend path; not a standalone #158 fix.

## Implementation status (built 2026-10-18 21:23, before the advised reboot)

- `NootedRed/UserPatches.{hpp,cpp}` (new, by teammate `lilu-userpatch`) is a native user-space page
  patcher: on macOS 11+ it routes `_cs_validate_page` (and best-effort `_cs_validate_range`), matches
  a complete 4 KiB driver-file page, and writes the replacement into the kernel's page image only
  after code-signing validation; on ≤10.15 it uses Lilu's `onProcLoad`. Opt-in via `-NRedGLFix`,
  force-off via `-NRedGLFixOff`, no PANIC on failure.
- The A1 patch table is filled: page 0xE000 of `AMDRadeonX5000GLDriver` (exact 4096-byte image in
  `UserPatches.cpp`), site page+0x81 (file 0xE081): `C7 47 78 04 00 00 00` → `C7 47 78 01 00 00 00`
  (`numShaderEngines` 4→1, making `rec+0x64` CU count 8 instead of 32 on Renoir).
- `NRed.cpp` includes `<UserPatches.hpp>` and calls `UserPatches::singleton().init()` from
  `NRed::init()`. Default is still **off** (`kGLFixDefaultEnabled=false`); enable with `-NRedGLFix`.
- `xmake f -m release -y && xmake -y` succeeds; artifact:
  `build/macosx/x86_64/release/NootedRed-0.9.0-RELEASE.zip`.
- **Not runtime-tested.** The box was in a GPU reset loop; after a clean reboot the next step is to
  install this kext (via the user's OpenCore/EFI or /Library/Extensions mechanism), add
  `-NRedGLFix` to boot-args, reboot, then run the *safe* `--inspect`/`--link` checks and only then a
  single `--render --yes` A/B. Key expected signal: `GL_MAX_COMPUTE_UNITS` 32→8 and dual-source
  case 5 reaching ~`64,0,191,255`.
- If A1 does not fix the GL dual-source hang, try A2: NOP `74 12` at GL driver 0x8146
  (`_glrAMD_GFX9_UpdateHwCbDualQuadMode`) as a diagnostic, and/or port the legacy-blend idea to the
  Metal driver for Chromium's ANGLE Metal path.

## Deployment state at 21:28 (before reboot)

- The active EFI kext `/Volumes/NO NAME/EFI/OC/Kexts/NootedRed.kext` already has **MD5
  `731dc1d4c2c0809699f2fea91a00097b`**, identical to the A1 build at
  `build/macosx/x86_64/release/NootedRed.kext/Contents/MacOS/NootedRed`.
- `/Volumes/NO NAME/EFI/OC/config.plist` `NVRAM/Add/.../boot-args` is
  `keepsyms=1 debug=0x144 itlwm_he=1 -NRedGLFix` (config.plist mtime 21:27), so OpenCore should
  enable the user-space patch on the next boot. NVRAM itself still lacks `-NRedGLFix`, but OpenCore
  applies the config value at boot.
- Therefore: **reboot is the only remaining step before testing**. After reboot, first check that
  the kext loaded and `-NRedGLFix` was seen (`log show --last boot | grep -i UserPatch`), then use
  the safe inspect/link modes; do not run render before confirming no GPU reset loop.

## What is verified

1. **Minimal repro (offscreen CGL/FBO, 64x64, no drawable needed for FBO path)**:
   - `glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)` works (case 3 of
     `/tmp/glblend3.c` → 128,0,128,191 as expected).
   - `glBlendFuncSeparate(GL_SRC1_COLOR, GL_ONE_MINUS_SRC1_COLOR, GL_ONE, GL_ZERO)` with a
     dual-source fragment shader (`layout(location=0,index=0/1) out vec4 c0/c1`) **hangs/resets the
     GPU**: draw is silently dropped, readback returns clear colour, and `*.gpuRestart` reports are
     produced. This matches maintainer comment 2024-08-25: "it's dual source blend… blending
     functions in general".
   - `/tmp/glblend3.c` matrix: cases 0–4 OK, case 5 (dual-source SRC1) broken.
   - `GL_ARB_blend_func_extended` is exposed, `GL_EXT_blend_func_extended` is not;
     `GL_MAX_DUAL_SOURCE_DRAW_BUFFERS=1`.
   - Crash logs from the probes show GPU reset (`recoveryCount` in `ioreg` went 0→6) and
     `AMDRadeonX5000GLDriver` page faults; the earlier SIGSEGV stack from a no-drawable probe
     (`glrAMD_GFX9_UpdateHwExportBlockState ← UpdateDrawBufferInfo ← glClear`) is a separate
     no-drawable issue, not the dual-source bug.

2. **Driver state at call time** (interposer `/tmp/glhook2.c` + `/tmp/libglhook2.dylib`, logs from
   `GLHOOK_MODE=hwinfo`):
   - `_gfx9_HwInfoInitData(GFX9_HwInfoRec *hwInfo, AMD_GET_HW_INFO_VALUES *arg2, uint32_t arg3)`
     in `AMDRadeonX5000GLDriver` (15.8.1, driver 7.0.25) is at file offset **0xdf40**.
   - On Renoir 0x1638, it is called twice with `arg3 = 0x00010000` (bit 16 of the masked
     `*(ctx->8+0x2e8) & 0xFFF0000`). `testl $0x70000` therefore takes the **Vega dGPU hardcoded
     branch**.
   - Resulting `GFX9_HwInfoRec` (offsets): `family=0x8d`, `totalNumComputeUnits=0x20` (32!),
     `numShaderEngines=4`, `numShaderArrays=1`, `numGsWavesPerVGT=0x20`,
     `numOffChipLdsBuffersPerSE=0x7f`, `numParameterCacheLines=0x1000`, `numTCC=0x10`,
     `reserved=0x4d`, `chip=0xc1`. For Renoir the kernel reports 8 CUs / 1 SE / 1 SH
     (`GPUConfigurationVariable`: NumSE=1, NumSH=1, NumCUPerSH=8; `GB_ADDR_CONFIG=0x24000042`).
   - A first attempt to correct these fields in the interposer (`hwInfo+0x64=8, +0x78=1, +0x80=1,
     +0x84=0x10, +0x88=0x7f, +0x8c=0x1000, +0x90=2, +0xa0=0x0d, +0xac=0x42`) did **not** fix the
     dual-source draw. This may be because the correct values/flags are different, because the
     patch was applied after the driver had already cached derivative state, or because the
     dual-source path is a separate bug. Do not treat this as conclusive.
   - The maintainer's 2026-07-13 screenshot is the same `gfx9_HwInfoInitData` logic; the
     prototype's addresses (0x426111+) do not map to our 15.8.1 GL driver offsets.

3. **Community fix (strongest existence proof, not a drop-in)**: fork
   `steve12311/NootedRed` (`/tmp/nr-fork`, master 1983f32, 2026-10-07) implements a user-space
   driver patcher inside NootedRed:
   - kernel hook `_shared_region_check_np`, walks process VM map, validates dyld shared cache
     UUID/full-function hashes, writes only process-private COW pages (mach_vm_protect/copyout),
     restores RX; **never edits the file** (`NootedRed/UserSurfaceSync.cpp`).
   - `-NRedLegacyBlend` NOPs a 2-byte RB+ capability branch (`74 28` → `90 90`) in the Metal
     pipeline constructor (`-[GFX9_MtlRenderPipelineState initWithDevice:...]`), so
     `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD` is set on iGPU. Docs claim Cezanne 5800H user fixed
     Chrome/WeChat artifacts. Data: `NootedRed/UserSurfaceSyncData.hpp`
     (`LegacyBlendPatches[2]`, cache offset 0x310C77708 for Tahoe).
   - Gate: Darwin 25 / macOS 26 + shared-cache UUID 0x... ; our box is Darwin 24.6 / macOS 15.8.1,
     cache UUID differs, and the patched driver is `AMDRadeonX5000MTLDriver` not the GL driver.
   - Mechanism of the gate per docs: when the RB+ capability report is missing, the code skips
     `dualSource || !allowRBPlus`; NOPing the branch forces `DISABLE_DUAL_QUAD` (RB+ dual quad
     disabled) on iGPU. This is the same "RB+ does not work with dual source" constraint documented
     in Mesa (`si_create_blend_state_mode`: "Disable RB+ blend optimizations for dual source
     blending", `S_028808_DISABLE_DUAL_QUAD(1)`).
   - Direct reuse is blocked by OS/cache version, but it validates (a) the dual-quad/RB+ root
     cause and (b) a user-space COW-page patch delivery mechanism that avoids on-disk changes.

4. **PRIMARY ROOT-CAUSE CANDIDATE (from `analysis/gl-hwinfo.md`, verified statically)**: arg2 is a
   byte copy of the kernel `sHardwareInfo` (0x204 bytes) fetched via
   `IOAccelDeviceGetConnect` + `IOConnectCallMethod(selector 0x100)`. arg3 is
   `(device+0x2e8) & 0xFFF0000`; its bits [18:16] are the family code (0x10000=Vega10), so Renoir
   always takes the hardcoded Vega10 branch. That branch writes **`GFX9_HwInfoRec+0x78 = 4`**
   (num shader engines) in all three branches; `rec+0x64 = rec+0x60 * rec+0x78 * rec+0x80` is used
   as OpenCL "max compute units" and for ring validation, so Renoir gets **32 instead of 8**.
   Patch **A1**: GL driver file offset `0xE081`, 7 bytes
   `C7 47 78 04 00 00 00` → `C7 47 78 01 00 00 00` (same at 0xE0CC, 0xE109 for Vega12/20).
   Unique context pattern: `C7 07 8D 00 00 00 C7 47 78 04 00 00 00 C5 F8 28 05 50 FE 0D 00`
   at 0xE07B. Pages to snapshot: 0xE000, 0x68000, 0x7D000, 0x5E000.
   **Important correction to earlier report**: the RB+ blend-opt gates test `rec+0xA0` bit 1, and
   only the Vega12 branch sets it (0x4F); Vega10/Vega20 set 0x4D, so on Renoir those opt packets are
   **already skipped**. The bug is therefore more plausibly the wrong SE/CU/pipe/tiling model than
   the RB+ opt state. Do **not** base the fix on the fork's `74 28` dual-quad patch without
   confirming; the fork patch is a Metal-path analogue and may not match this GL driver's state.
   Verify A1 after reboot by checking `GL_MAX_COMPUTE_UNITS`/`CL_DEVICE_MAX_COMPUTE_UNITS` changes
   32→8 and by re-running the dual-source blend probe.

5. **Lilu user patcher limitation**: `../AppleForge/Lilu/Lilu/Sources/kern_start.cpp:247` sets
   `isUserDisabled = ... || getKernelVersion() >= BigSur`; `UserPatcher::init/registerPatches`
   return early on macOS 15.8.1. Pure `lilu.onProcLoad()` is a silent no-op on this OS. A native
   `_cs_validate_page` (vnode page-in) or `_shared_region_check_np` (shared-cache COW) hook is
   required.

## Candidate fixes (to implement after reboot)

### A. GL driver (our minimal repro, bundle not shared cache) — **A1 is now primary**
Based on `analysis/gl-hwinfo.md` (verified statically):
- **A1**: `GFX9_HwInfoRec+0x78` 4→1 at file offset **0xE081** (7 bytes,
  `C7 47 78 04 00 00 00` → `C7 47 78 01 00 00 00`); also 0xE0CC and 0xE109 for the other branches.
  This fixes `rec+0x64` CU product 32→8 and the pipe/bin-table model. Context pattern at 0xE07B:
  `C7 07 8D 00 00 00 C7 47 78 04 00 00 00 C5 F8 28 05 50 FE 0D 00`.
- **A2 (diagnostic)**: `_glrAMD_GFX9_UpdateHwCbDualQuadMode` @ 0x8134: after A1, if dual-source still
  fails, try `74 12`→`90 90` at **0x8146** (the 15.8.1 analogue of the fork's `74 28`; forces the
  `DISABLE_DUAL_QUAD` computation path). Note: the earlier claim that bit1 of `rec+0xA0` gates RB+
  opt was wrong — in this build only the Vega12 branch sets it; on Renoir those packets are already
  skipped. Do not trust the pre-reboot `rbplus`/`hwinfo` interposer results.
- **Do NOT force `83 E0 FE`→`83 C8 01` at 0x8160** as the primary fix; it was based on a mistaken
  reading of the RB+ gate and was never tested.
- Verify A1 with `/tmp/glblend3` or `tools/gl_blend_probe --render --yes` **after** a clean reboot.
  Expected: `GL_MAX_COMPUTE_UNITS` 32→8; case 5 (dual-source) changes from `0,0,255,255` to
  ~`64,0,191,255` if the SE model is the cause. If A1 does not fix it, A2 is the next cheap probe.

### B. Metal driver (what Chromium/Electron on macOS 15 likely uses)
Port the fork's LegacyBlend idea to Darwin 24.6 / 15.8.1:
- Extract/locate `AMDRadeonX5000MTLDriver` from
  `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_x86_64h`
  (`dsc_extractor.bundle` rejected the cache on this box with a page code-signature error, so a
  manual cache-header/mapping parser is needed).
- Find the analogous `74 28` RB+ capability branch in the 15.8.1 Metal pipeline constructor
  (`-[GFX9_MtlRenderPipelineState initWithDevice:pipelineStateDescriptor:vertexVariant:fragmentVariant:]`
  or successor) and NOP it to `90 90`. Confirm the resulting `CB_COLOR_CONTROL` has
  `DISABLE_DUAL_QUAD=1` via a Metal `--inspect-only` test before any render.
- Delivery: native kernel hook on `_shared_region_check_np` (fork pattern: process-private COW
  pages only, UUID/patch guards, rollback), or a narrower `_cs_validate_page` patch if the target
  page is file-backed. **Do not patch the on-disk cache.**

### C. HwInfo (maintainer's lead)
Correct `gfx9_HwInfoInitData` for Renoir (family AI + isRaven/isDcn flags, 1 SE, 8 CUs, 2 TCC or
whatever the UBM struct expects) instead of the Vega branch. Our first field-correcting attempt
did not fix dual-source in the interposer; it needs a clean-reboot A/B and likely more accurate
field mapping (we could not resolve all `GFX9_HwInfoRec` field semantics from symbols alone).
This remains a plausible independent fix for tiling/blit corruption but is **not** yet verified to
address the dual-source GPU hang.

## Implementation plan for NootedRed (after reboot)
1. `lilu-userpatch` (teammate) is writing `NootedRed/UserPatches.hpp/.cpp` with a native
   `_cs_validate_page` page-patch engine (Lilu API disabled on Big Sur+). Integrate into
   `NRed::init()` behind an opt-in boot arg (`-NRedGLFix`), with graceful failure and no PANIC.
2. Add candidate A byte patch first (GL bundle, file-backed → `_cs_validate_page` works), with the
   exact 15.8.1 find bytes and version gating. Build release+debug.
3. If a clean-reboot test shows candidate A fixes the GL repro, decide whether to also implement
   candidate B (Metal/shared cache, COW/branch patch) for Chromium's actual macOS path.
4. Keep HwInfo correction as a separate experimental option only if evidence supports it.

## Files/artifacts for resume
- `/tmp/x5000gl.dis` full GLDriver disassembly; `/tmp/glblend3.c`, `/tmp/glblend2.c`,
  `/tmp/glhook2.c`, `/tmp/libglhook2.dylib`, `/tmp/cglprobe.c`.
- `/tmp/sys.kc`, `/tmp/HWLibs.kext.macho`, `/tmp/X5000.kext.macho` (kernel kext extraction).
- `/tmp/nr-fork` steve12311 fork clone (read `docs/metal-rendering-fix.md`,
  `NootedRed/UserSurfaceSync.cpp`, `NootedRed/UserSurfaceSyncData.hpp`).
- Teammate deliverables in workspace: `analysis/gl-hwinfo.md` (pending), `analysis/kernel-leverage.md`
  (pending), `analysis/lilu-userpatch.md` + `NootedRed/UserPatches.*` (pending),
  `analysis/repro-plan.md` + `tools/gl_blend_probe.c` (done).
- Baseline build is green (`xmake f -m release -y && xmake -y`).

## A2 result (post-reboot, 21:35-21:36) — decisive

- A1 alone was confirmed applied in the running system via a DYLD interposer:
  `[hwi] arg3=0x00010000 family=0x8d totalCU=8 SE=1 arr=1 tcc=16 reserved=4d chip=c1`
  (was totalCU=32, SE=4). So the kernel `_cs_validate_page` page patch works and A1 is in effect.
- With A1 applied, a valid-drawable AppKit/OpenGL 4.1 test still failed dual-source:
  `dual 0,0,255,255` instead of `64,0,64,255` (the earlier "expected 64,0,191" was a math error;
  with c0=(1,0,0,1), c1=(0.25,0.5,0.75,1), dst=(0,0,1,1) and
  blendFunc=(SRC1_COLOR, ONE_MINUS_SRC1_COLOR) the correct result is `(64,0,64,255)`).
- **A2 (the real fix)**: patch `83 E0 FE` → `83 C8 01` at GL driver **0x8160** (page 0x8000,
  page offset 0x160; the same 3-byte sequence also occurs at page offset 0x68, so skip=1). This
  forces `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD=1` in `_glrAMD_GFX9_UpdateHwCbDualQuadMode`. With A2
  injected into the running (A1-patched) driver, the same test produced **`64,0,64,255` — correct
  dual-source blending**, and solid/alpha rendering remained correct. A2b-only rerun at 21:36
  produced no new GPU reset. (`a2a`, NOP of `74 12`, did **not** fix it; do not use it.)
- A2 has been added to `NootedRed/UserPatches.cpp` as a second `PagePatch` with the exact 4 KiB
  page 0x8000 image; release build is green. The updated kext was copied to
  `/Volumes/NO NAME/EFI/OC/Kexts/NootedRed.kext` (MD5 of the binary
  `4630e1b9199a134f3b8604c6285e1edd`); the A1-only kext was backed up to
  `build/efi-backup/NootedRed-A1only.kext`. EFI `boot-args` already carries `-NRedGLFix`.
- **Next step: reboot once more to load the A1+A2 kext.** After boot, verify with the interposer
  that `totalCU=8` and that dual-source returns `64,0,64,255`, then watch for GPU resets. One
  residual `Kernel_*.gpuRestart` (21:35:21, WindowServer, channel 23 GFX) was produced during the
  earlier experiment matrix (which included the bad `a2a`/combo runs); the A2b-only rerun did not
  reproduce it, but the reboot+quiet-period test is the real confirmation.

## Metal / Chromium path (verified in user space, 21:44-21:47)

- On this machine Chromium/Electron **uses Metal**: the running Electron GPU process (`DeepSeek Harness
  Helper --type=gpu-process`) maps `AMDRadeonX5000MTLDriver` + `libANGLE-shared.dylib`, not the GL
  driver. The original #158 stack and our GL repro are GL, but modern Chromium/Electron is Metal, so
  the GL patch alone is not enough for Chrome/Electron.
- A minimal Metal pipeline test (no draw first) showed `GFX9_MtlRenderPipelineState.m_members`
  `+0x28` (CB_COLOR_CONTROL) = `0x00cc0010` for **both** single and dual-source pipelines, i.e.
  `DISABLE_DUAL_QUAD=0`. This is the Metal analogue of the bug.
- **Metal fix (verified in user space)**: in `AMDRadeonX5000MTLDriver`'s pipeline setup, patch the
  three bytes `83 E1 FE` (`and ecx, ~1`) at VA `0x7ffb087b31c0` (cache-base relative
  `0x3087b31c0`; image-relative `0x5c1c0`) to `83 C9 01` (`or ecx, 1`). This is the `DISABLE_DUAL_QUAD`
  computation (`and ecx,~1; or ecx,eax`) inside the render-pipeline state setup. With the patch
  applied in-process, both single and dual pipelines get `CB_COLOR_CONTROL=0x00cc0011`
  (`DISABLE_DUAL_QUAD=1`), and a real Metal render (32x32, blit + CPU comparison) **passes for both
  cases** with no GPU reset (single `96,128,160,191`; dual `128,160,192,223`).
- The Metal driver is in the dyld shared cache, so this needs the shared-cache patch path, not the
  file-backed GL bundle path. The current `UserPatches.cpp` adds the exact 4 KiB
  `AMDRadeonX5000MTLDriver` page 0x7ffb087b3000 (from `.03` cache) as a third `PagePatch`; the native
  `_cs_validate_range` backend will match it only if shared-cache pages are validated after the kext
  installs its hooks. **This delivery is not yet runtime-verified**; if it does not take effect, the
  next step is a minimal `_shared_region_check_np` COW-page hook (the steve12311 fork's mechanism).
- EFI now has the A1+A2+Metal build (binary MD5 `4f8cef18fa2893f9b84885c71a0a4a6d`); previous
  A1+A2 backup in `build/efi-backup/NootedRed-A1A2.kext`. `-NRedGLFix` remains in boot-args.

## FINAL VERIFICATION (2026-10-18 21:50, after third reboot)

- Loaded kext is the A1+A2+Metal build (`kextstat` size 0x274000; EFI binary MD5
  `4f8cef18fa2893f9b84885c71a0a4a6d`), boot args include `-NRedGLFix`, no new
  `Kernel_*.gpuRestart` after boot.
- **GL path verified**: with the loaded kext, the internal `GFX9_HwInfoRec` reports
  `totalCU=8, SE=1` (A1 active), and a valid-drawable GL test:
  `solid=255,0,0,128`, `alpha=128,0,128,191`, `dual=64,0,64,255` — all correct, no GPU reset.
- **Metal path verified through the actual NootedRed page-patch delivery** (not just an
  in-process experiment): a fresh Metal test process reports
  `CB_COLOR_CONTROL=0x00cc0011, DISABLE_DUAL_QUAD=1` for both single and dual-source pipelines,
  and a real Metal render/blit/CPU-compare passes:
  `single 96,128,160,191`, `dual 128,160,192,223`, no GPU reset.
- This proves the native `_cs_validate_range` page-patch backend reaches the shared-cache
  `AMDRadeonX5000MTLDriver` page as well as the file-backed GL driver pages.
- Remaining validation: run the user's actual Chrome/Electron workload for a while and watch for
  new `*.gpuRestart`/corruption; the minimal Metal dual-source case is fixed. Rollback: remove
  `-NRedGLFix` (or restore `build/efi-backup/NootedRed-A1A2.kext` / the original EFI kext).

## Do not
- Do not run CGL/Metal/OpenGL render tests before reboot; they reset the GPU in seconds.
- Do not patch the on-disk system cache or system kexts; use process-private/in-memory patches.
- Do not trust the `rbplus`/`hwinfo` interposer results from the pre-reboot session; the system was
  already resetting.
