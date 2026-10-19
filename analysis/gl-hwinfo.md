# `_gfx9_HwInfoInitData` (AMDRadeonX5000GLDriver 7.0.25, macOS 15.8.1) — RE report

Status: static analysis complete for the user-space `GFX9_HwInfoRec` init path. Patch candidates are
given as exact 15.8.1 file offsets/bytes plus version-general byte patterns. Nothing here was
executed on the GPU; all claims marked **[verified]** are reproducible from the commands in §9.

Target binary: `/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver`
(Mach-O x86_64h, 1,808,640 bytes, driver 7.0.25). For this bundle **file offset == vmaddr** (verified:
file offset 0xdf40 contains `55 48 89 e5 …` for `_gfx9_HwInfoInitData`), so all offsets below can be
used directly with `xxd -s`.

---

## 1. TL;DR

1. `_gfx9_HwInfoInitData(rec, hwInfo, flags)` fills a **180-byte (0xb4) `GFX9_HwInfoRec`** at
   sharegroup/context + 0x168. Full write map in §3; it is a straight projection of the kernel-side
   `sHardwareInfo` (0x204 bytes, §2) into GL-driver ABI.
2. **arg2 is a kernel copy of `sHardwareInfo`**: `AMDAccelDevice::getHardwareInfo(_sAMD_GET_HW_INFO_VALUES*)`
   (X5000 kext, 0x4364dde) does `memcpy(out, AMDHWInterface::getHWInfo(), 0x204)`; `getHWInfo()` is the
   vtable slot 0x1c0 of the hardware object and simply returns `&sHardwareInfo` at `hardware+0xd0`
   (getter at 0x43c6e8c = `lea 0xd0(%rdi),%rax; ret`). User space obtains it with
   `IOAccelDeviceGetConnect` + `IOConnectCallMethod(conn, selector 0x100, …, out=0x204, &size)`.
3. **arg3 is `(*(ctx+8) + 0x2e8) & 0xFFF0000`**. `device+0x2e8` is a packed descriptor built by the
   GL device layer: low 16 bits = PCI device ID, bits [18:16] = family code (0x10000=Vega10,
   0x20000=Vega12, 0x40000=Vega20), bits [31:28] = ASIC variant index (verified from
   `_glrInitializeDevice`, 0x48ed8). **Consequence: if the family bits are zero the driver skips the
   whole family branch and leaves `rec.family = 0`** (addrlib then rejects it).
4. The function **hard-codes Vega dGPU configuration** in all three branches. In particular it writes
   **`rec+0x78 = 4`** ("number of shader engines") for Vega10/12/20. Renoir has **1 SE**; the CU
   count product `rec+0x64 = rec+0x60 * rec+0x78 * rec+0x80` (verified: used verbatim as OpenCL
   "max compute units" in `_glrAMD_GFX9_GetDeviceComputeConfig`) therefore becomes **32 instead of 8**
   on Renoir. This is the concrete numeric bug in the maintainer's screenshot.
5. Setting `rec.family = 0x8E` (RV) is **not** a drop-in fix: the *user-space* addrlib in this bundle
   only implements `FAMILY_AI` (`Gfx9Lib::HwlConvertChipFamily` at 0x7d940: `cmp esi,0x8d; jne →
   return ADDR_CHIP_FAMILY_AI` with **no settings at all**), and `Addr::Lib::Create` (0x681a0) rejects
   any chip family except 0x8D/0x8F. A family switch therefore needs 3 extra patches and still only
   yields Vega12-ish addrlib settings (no `isRaven`/`isDcn1`/`isDcn2`).
   Recommendation: **keep family 0x8D** (this mirrors NootedRed's own kernel-side
   `wrapHwlConvertChipFamily`, which returns `ADDR_CHIP_FAMILY_AI` for RV) and fix the counts instead.
6. Surprising **[verified]** fact that corrects the earlier report: the "RB+ blend optimisation" gates
   in this build test **bit 1 (0x2) of `rec+0xA0`**, and only the **Vega12** branch sets that bit
   (`0x4F`); Vega10/Vega20 set `0x4D` (bit 1 clear). So with the current Renoir behaviour (Vega10
   branch) `SX_BLEND_OPT_CONTROL`, export-block optimisation and the CB dual-quad state are **already
   skipped**. The corruption therefore most plausibly comes from the wrong pipe/CU/tiling model
   (`rec+0x78`, family-driven addrlib settings), not from those packets — but this must be confirmed
   on hardware (§8).
7. Candidate patch set for testing (all 15.8.1, exact bytes in §6):
   - **A1 (primary, low risk):** `rec+0x78` 4 → 1 in the Vega10 branch. Fixes CU count 32→8 and the
     pipe/bin-table model. 7 bytes at file offset 0xe081.
   - **A2:** same 7-byte change in the Vega12 and Vega20 branches (offsets 0xe0cc, 0xe109) so a future
     revision-based branch cannot reintroduce the bug.
   - **B (family, NOT recommended alone):** `0x8d → 0x8e` in 3 branches + 3 addrlib/UBM sites.
   - **C (blend experiment):** force `CB_COLOR_CONTROL` dual-quad state on (nop the `je` at 0x8146)
     if §8 instrumentation shows `rec+0xA0 bit1` matters.
8. Applying any of this needs the user-space page-patcher (see `analysis/lilu-userpatch.md`); Lilu's
   user patcher is dead on macOS ≥ 11. All patch sites are inside `__TEXT:__text`, so the
   `NootedRed/UserPatches` page-image table must contain the full 4 KiB pages
   `0xE000`, `0x68000`, `0x5E000`, `0x7D000` of this exact bundle.

---

## 2. Call graph and argument provenance (all verified)

### 2.1 User-space callers

`_glrInitializeShareGroup` (0x1576), share-group path:

```asm
157a:  subq $0x238,%rsp
1597:  leaq -0x234(%rbp),%r12        ; r12 = local 0x204-byte hwInfo buffer (zeroed with memset)
15ab..15d7: zero 0x168..0x208 of the sharegroup object       ; rec (0xb4) + settings are pre-zeroed
15df:  movq 0x8(%rbx),%rax           ; rbx = sharegroup; rax = sharegroup->device (ctx)
15e3:  movq 0x230(%rax),%rdi
15ed:  callq IOAccelDeviceGetConnect ; io_connect_t for the accelerator
15f2..1612: IOConnectCallMethod(conn, 0x100, NULL,0,NULL,0, NULL,NULL, buf, &size=0x204)
1626:  movq 0x8(%rbx),%rax
162a:  movl $0xfff0000,%r13d
1630:  andl 0x2e8(%rax),%r13d        ; ← arg3 = (ctx+0x2e8) & 0xFFF0000
1637:  movq %r15,%rdi                ; arg1 = sharegroup + 0x168  (GFX9_HwInfoRec)
163a:  movq %r12,%rsi                ; arg2 = 0x204-byte IOConnectCallMethod output
163d:  movl %r13d,%edx               ; arg3
1640:  callq _gfx9_HwInfoInitData
1645:  _gfx9_HwWorkAroundsInitFlags(rec+0xb0, arg3, rec+0x10)
1655:  _glrAMD_GFX9_InitDriverSettings(rec, &rec+0xb4)   ; driver settings struct at ctx+0x21c
16f5:  _glrAMD_GFX9_AddrLibInit(&ctx+0x228, ctx)         ; reads rec+0x00 / rec+0x10
```

`_glrAMD_GFX9_InitComputeDevice` (0x1cf8f) allocates its own rec (`malloc(0xb4)`) and calls the same
function at 0x1d07e with the *same mask*: `andl 0x2e8(%rbx), %r12d` with `%rbx` = device. The rec is
then at `computeDevice+8`, workaround flags at `rec+0xb0`.

`_glrAMD_GFX9_GetDeviceComputeConfig` (0x1d12f, installed as `glrPopulateDeviceConfig`) uses
`rec = computeDevice->8` and: `rec+0x64 = rec+0x60 * rec+0x78 * rec+0x80` stored as OpenCL "max
compute units" (config+0x10) and `<<6` into config+0x14. **This is the CU-count proof.**

`_amdUbm_HWL_Init` (0x5ee3a) repeats the whole dance (same two IOKit calls, same 0x204 copy) and passes
`sHardwareInfo+0xf0/+0x108/+0x8/+0x18/+0xa0/+0x28..0x40` into the UBM blit HWL struct, with
`hardcoded family 0x8d` at ubmStruct+0x18 and revision at +0x1c (that is the second function the
maintainer named).

### 2.2 Kernel side: what arg2 actually contains

`AMDRadeonX5000_AMDAccelDevice::getHardwareInfo` (X5000 kext 0x4364dde):

```asm
4364dde: ; (this, _sAMD_GET_HW_INFO_VALUES *out)
4364df8: movq 0x108(%rdi),%r15         ; accelerator hardware object
4364dff: leaq 0x90(%r15),%r12          ; lock
4364e22: movq 0x1a38(%r15), %rdi       ; AMDHWInterface object
4364e2a: movq (%rdi),%rax
4364e50: callq *0x1c0(%rax)            ; vtable slot 0x1c0 = getHWInfo() → &sHardwareInfo
4364e56: movl $0x204,%edx
4364e5e: callq memcpy                  ; out = sHardwareInfo[0x204]
```

* vtable base of the hardware interface object = `0x459c5d0` (from the Vega10Hardware constructor,
  `lea 0x1d5b22(%rip),%rax ## 0x459c5d0`). Entry `+0x1c0` decodes (kext chained-fixup form
  `raw - 0x40000040000000`) to **0x43c6e8c = `lea 0xd0(%rdi),%rax; ret`**, i.e.
  `sHardwareInfo` lives at `hardwareObject + 0xd0`, size 0x204.
* slot `+0x1c8` = `AMDHardware::updateHWInfoClocks`; slot `+0x6a8` = `AMDVega10Hardware::readChipRevFromRegister`.
* `AMDHardware::initHWInfo` (0x43cba44) zeroes `this+0xd0` for 0x204 bytes and then fills it (see §2.3).
* `AMDHardware::init` (0x43c9226) stores the four PCI config u16s at `this+0x2fc/0x2fe/0x300/0x302`,
  follows vtable `*0x6a8` = `readChipRevFromRegister` into `this+0x2f8`, and `readChipRevFromRegister`
  for Vega10Hardware returns **1 or 2** (`cmpl $1; sete; incl`), *regardless of the real ASIC*.
* `AMDAccelDevice`'s post-copy validation (log strings at 0x4445c64/0x4445ce0) confirms semantics:
  `deviceID` @ +0x00, `numRasterPipe` @ +0x18, `numShaderPipes` @ +0x20,
  `refClkFreq` @ +0xc0, `sysClkFreq` @ +0xc8, `memClkFreq` @ +0xd0, `cgRefClkFreq` @ +0xd8.

### 2.3 `sHardwareInfo` layout as far as traced (kernel writes, all 15.8.1)

| off | write site | value | note |
|---|---|---|---|
| 0x00 | `initHWInfo` `qword [this+0x2fc]` | PID + 3 more u16s | +0 is the PCI **device ID** (0x1638 on Renoir; verified: GL renderer-ID switch compares `hwInfo+0` low16 with Vega IDs) and the following u16s are vendor/subsystem IDs in `configRead16` order |
| 0x08 | `initHWInfo` `u32 [this+0x2f8]` | chipRev | `= readChipRevFromRegister()` = **1 or 2** for Vega10Hardware class |
| 0x10 | `initHWInfo` `[this+0x18]->vt+0x1c0()` | family-ish u32 | HW-handler/accelerator value |
| 0x18 | `initHWInfo` `u32 [this+0x44]` | numRasterPipe | total RB+; no writer for hardware+0x44 found in X5000 `__text` (template/zero init?) |
| 0x20 | `initHWInfo` `u32 [this+0xa4]` | active CUs per SE | = min(Σ SH-table CUs, `hwMaxCUs`); NootedRed sets hwMaxCUs=8 for Renoir |
| 0x28 | (not written by traced init) | ? | GL uses `tzcnt` of it for `rec+0x9c` |
| 0x88 | `initHWInfo` `u32 [this+0x64]` | seCount | NootedRed: 1 (Renoir) |
| 0x90 | `initHWInfo` `u32 [this+0x6c]` | shCount | NootedRed: 1 |
| 0xa0 | `initHWInfo` `u32 [this+0x48]` | HW caps dword | set in `AMDGFX9Hardware::setupAndInitializeHWCapabilities` |
| 0xa8 | `initHWInfo` `u32 [this+0x4c]` | caps | |
| 0xc0..0xd8 | `initHWInfo`, ATOM table #4 (4×u64) | clocks | these are the values the driver divides by 100 |
| 0xe0 | `[this+0x378]->vt+0x1d0()` | u64 | shifted right 20 → MB, becomes `rec+0x14` |
| 0xe8/0xec | ATOM table #8 | u32s | |
| 0xf0..0x110 | (other init) | u32s | become `rec+0x2c..0x3c` |

`AMDGFX9Hardware::setupAndInitializeHWCapabilities` (0x43ba3d8) computes `this+0xa4`
(`min(totalCUs, this+0xa0)`), `this+0xa8` (Σ CUs), and reads GC registers 0x63e/0x63f/0xd4/0xd5 into
`this+0x48/0x50/0x5c/0x60`. NootedRed's `X5000::wrapSetupAndInitializeHWCapabilities` forcibly sets
`seCount=1, shCount=1, hwMaxCUs=8` (Renoir) before calling it, so **`sHardwareInfo+0x20 == 8`** and
`+0x88 == 1` on Renoir.

`_sAMD_GET_HW_INFO_VALUES` is therefore a byte mirror of `sHardwareInfo`; user space never writes it.

### 2.4 arg3 (`device+0x2e8`, packed descriptor; verified in `_glrInitializeDevice` 0x48ed8)

```asm
48eef: movl 0x2e8(%rdi),%r13d
48ef9: andl $0xfff0000,%r15d
48f00: cmpl $0x40000,%r15d ; je Vega20
48f09: cmpl $0x20000,%r15d ; je Vega12
48f17: cmpl $0x10000,%r15d ; je Vega10, else "unknown"
48fc7: shrl $0x1c,%r13d            ; bits [31:28] = ASIC variant used for renderer names
48ff9: movzwl %ax,%ecx             ; low 16 = PCI device ID (!) compared with Vega IDs 0x6860.., 0x687f, 0x66af, …
```

So `(dev+0x2e8) & 0xFFF0000` is non-zero **iff** the device layer has classified the GPU as a Vega
family member. `testl $0x70000,%eax; je 0xe0b5` in `gfx9_HwInfoInitData` is the same test.

Practical consequence (medium-high confidence): if arg3 were 0 on Renoir, the driver would take the
"no-family" path (see §4, `0xe0b5`): `rec.family = 0` → `Addr::Lib::Create` returns
`ADDR_INVALIDPARAMS`, GL init would fail outright. Since Chromium actually renders (corrupted) on
Renoir, the Vega10 path must be taken, i.e. **the user-space device layer inherits a Vega10 class
from the kernel accelerator**, and the driver then uses the Vega10 branch below (`rec+0x78 = 4`).
This is exactly "no logic to handle the iGPUs, thus using Vega dGPU values".

---

## 3. `GFX9_HwInfoRec` field map (rec = 0xb4 bytes, written by `_gfx9_HwInfoInitData` 0xdf40–0xe167)

`rec+0x00` family, `+0x0c` deviceID, `+0x10` chipRevision, clocks in MHz (kernel values are in 10 kHz
units, `/100`), and the counts. Offsets marked "untouched" are left at the caller's pre-zeroed 0.

| off | size | source (`hwInfo+` = arg2 offset) | consumers (all verified call sites) | semantic | conf. |
|---|---|---|---|---|---|
| 0x00 | u32 | const **0x8D**, or 0 in no-family branch | `_glrAMD_GFX9_AddrLibInit` → `AddrCreate` chipFamily; GL addrlib `HwlConvertChipFamily` | **chip family** (0x8D = FAMILY_AI/Vega10) | high |
| 0x04 | u32 | — | — | untouched |  |
| 0x08 | u32 | — | — | untouched |  |
| 0x0c | u32 | `movzwl (hwInfo), %edx` | renderer/device-id matching | **PCI device ID** (0x1638) | high |
| 0x10 | u32 | `hwInfo+0x08` (`movl`) | `AddrCreate` input+0xc (chipRevision); branch selector below | **chip revision** | high |
| 0x14 | u32 | `hwInfo+0xe0 >> 20` | — | size in MB (VRAM-ish) | med |
| 0x18 | u32 | `hwInfo+0xec` | — | ATOM table #8 value | low |
| 0x1c | u32 | `(u64 hwInfo+0xd8)>>2 /25` = `/100` | — | **cgRefClkFreq** | high |
| 0x20 | u32 | `hwInfo+0xc0 /100` | — | **refClkFreq** | high |
| 0x24 | u32 | `hwInfo+0xc8 /100` | — | **sysClkFreq** | high |
| 0x28 | u32 | `hwInfo+0xd0 /100` | — | **memClkFreq** | high |
| 0x2c–0x3c | 5×u32 | `hwInfo+0xf0/0xf8/0x100/0x108/0x110` | — | ATOM/GPU-info dwords | low |
| 0x40–0x4c | 4×u32 | `hwInfo+0x28/0x30/0x38/0x40` | — | HW caps dwords | low |
| 0x50–0x5f | — | — | — | untouched |  |
| 0x60 | u32 | `hwInfo+0x20` (movl) | `UpdateHwSpiVsLateAllocState` (`<<2`, waves math); CU product | **active CUs per SE** (8 on Renoir) | high |
| 0x64 | u32 | `rec+0x60 * rec+0x78 * rec+0x80` (end of function) | `GetDeviceComputeConfig` → CL max CUs; `ValidateShaderRings` (`0x46398`, `0x466ed`) | **total CU count** | high |
| 0x68–0x73 | — | — | — | untouched |  |
| 0x74 | u32 | `hwInfo+0x18` (numRasterPipe, total RB+) | `UpdateHwPrimBatchBinning` (`0x9a97`: `shrxl` by `bsr(rec+0x78)` → num SE; bin-size table index) | **total raster pipes** | high (use) |
| 0x78 | u32 | const **4** (all 3 branches), or 0 | bin table (`bsr` = num-SE log2), `InitDriverSettings` (`>=3`), `SpiVsLateAlloc` divisor, `ValidateShaderRings`, CU product | **number of shader engines** (Vega10/12/20 = 4; Renoir = 1) | high |
| 0x80 | u32 | const **1** | CU product; `SpiVsLateAlloc` divisor | secondary count factor (keep 1) | med |
| 0x84 | u32 | const 0x20 (=32) | — | unknown HW cap | low |
| 0x88 | u32 | const 0x7F (Vega10/Vega12) / 0x80 (Vega20) | `UpdateSpecialHwState` (`0xb1be`) | unknown HW cap | low |
| 0x8c | u32 | const 0x1000 (=4096) | — | unknown HW cap | low |
| 0x90 | u32 | const 0x10 (Vega10/Vega20) / 8 (Vega12) | — | unknown count/cap | low |
| 0x94–0x9b | — | — | — | untouched |  |
| 0x9c | u32 | `tzcnt(hwInfo+0x28)`, 0xFFFFFFFF if zero | `SpiVsLateAlloc` (`0xac7c`: `btrl` index into 16-bit SE mask) | log2/count of a SE/pipe mask | med |
| 0xa0 | u32 | `(orig \| 0x40)` then branch flags: **0x4D** (Vega10), **0x4F** (Vega12), **0x4D** (Vega20), **0x0C** (unknown family), **0** (arg3 bits clear) | `UpdateHwBlendOptState` (bit1 gate), `UpdateHwSxBlendOptState` (bit1→settings bit19), `UpdateHwExportBlockState` (bit1), `WriteDrawBufferRegs` (bit1), `WriteAllHwContextRegs` (bit1), `UpdateHwCbDualQuadMode` (bit1), `InitDriverSettings` (bit5 & bit1) | **feature flags**; bit1 = "RB+ opt / dual-quad paths" (only Vega12 sets it here) | high |
| 0xa4 | u32 | `hwInfo+0xa0` | — | HW caps | med |
| 0xa8 | u32 | `4*hwInfo+0x20 - 8` (=56 Vega10, 24 Renoir) | `SpiVsLateAlloc` (`0xab35`) | SPI/wave limit (unknown exact) | low |
| 0xac | u32 | `arg3 \| 0xC1` (Vega10/20: `\|0xC1`; Vega12: `\|0x1C2`; unknown-fam: `\|0x60`) | `WriteAllHwContextRegs` (`testb $0x6,0xac`) | family/HW flags | med |
| 0xb0 | u32 | **not here** — `_gfx9_HwWorkAroundsInitFlags` | `UpdateHwScissorState`/`WriteAllHwContextRegs` test bit 6 (0x40) | **workaround flags** = `0xFDF`, or `0xFFF` if chipRev==0x14, **0 if arg3&0x70000==0** | high |

Workaround flags function, full logic (0x58684):

```asm
58684: andl $0x70000,%esi        ; arg3 family bits
58690: cmpl $0x14,%edx           ; chipRev == 20 (Vega12 boundary)
58693: sete %al ; shl $5,%eax    ; 0x20 if rev==0x14
58699: orl $0xfdf,%eax
586a0: cmovel %esi,%eax          ; if family bits == 0 → flags = 0
586a3: movl %eax,(%rdi)          ; out (rec+0xb0)
```

---

## 4. Branch structure with exact bytes (file offsets)

```
df40  prologue; edx(arg3) → eax; ecx = rec->0xa0 (0); rec->0xa0 = ecx|0x40
df57  rec->0x0c = u16 hwInfo[0]                  ; deviceID
df5d  r8d = hwInfo[8]; rec->0x10 = r8d           ; chipRevision
df65  rec->0x14 = u64(hwInfo[0xe0]) >> 20
df73  rec->0x18 = hwInfo[0xec]
df7c  rec->0x1c = u64(hwInfo[0xd8])/100
df9d  rec->0x20 = u64(hwInfo[0xc0])/100
dfb4  rec->0x24 = u64(hwInfo[0xc8])/100
dfcb  rec->0x28 = u64(hwInfo[0xd0])/100
dfe2  rec->0x2c..0x3c = hwInfo[0xf0,0xf8,0x100,0x108,0x110]
e00f  rec->0x40..0x4c = hwInfo[0x28,0x30,0x38,0x40]
e027  rec->0x60 = hwInfo[0x20]; edx = that
e02d  rec->0x74 = hwInfo[0x18]
e035  rec->0x9c = tzcnt(hwInfo[0x28]) (0xFFFFFFFF if 0)
e04f  rec->0xa4 = hwInfo[0xa0]
e05b  rec->0xa8 = 4*hwInfo[0x20] - 8
e068  testl $0x70000,%eax          ; a9 00 00 07 00
e06d  je    0xe0b5                 ; 74 46   ← arg3.family == 0
                                        ; === family present: split by chip revision ===
e075  cmpl $0x13,%r8d ; e079 ja 0xe0c0   ; rev <= 0x13  → Vega10 (taken on Renoir: rev = 1/2)
e07b  rec->0x00 = 0x8d                  ; c7 07 8d 00 00 00
e081  rec->0x78 = 4                     ; c7 47 78 04 00 00 00   ← the SE/CU bug
e088  rec->0x80..0x8c = {1,0x20,0x7f,0x1000}   ; vmovaps from 0xedee0
e098  rec->0x90 = 0x10
e0a2  rec->0xa0 = 0x40|0x4d = 0x4D      ; 83 c9 4d
e0ab  eax |= 0xc1; rec->0xac = eax      ; 0d c1 00 00 00
e0b0  jmp 0xe138
e0b5  rec->0xa0 = ecx & ~0x40 (=0)      ; 83 e1 bf   ← arg3.family==0 path (no family, no counts)
e0be  jmp 0xe13e                        ; skips the CU product? no: e13e does the imul with 0s
e0c0  cmpl $0x27,%r8d ; ja 0xe0fd       ; rev <= 0x27 → Vega12
e0c6  rec->0x00 = 0x8d
e0cc  rec->0x78 = 4                     ; ← second copy
e0d3  rec->0x80..0x8c = {1,0x20,0x80,0x1000}
e0e3  rec->0x90 = 8
e0ed  rec->0xa0 = 0x4F                  ; 83 c9 4f   (bit1 set → RB+ opt paths ON)
e0f6  eax |= 0x1c2; rec->0xac = eax
e0fd  cmpl $0x31,%r8d ; ja 0xe14e       ; rev <= 0x31 → Vega20
e103  rec->0x00 = 0x8d
e109  rec->0x78 = 4                     ; ← third copy
e110  rec->0x80..0x8c = {1,0x20,0x80,0x1000}
e120  rec->0x90 = 0x10
e12a  rec->0xa0 = 0x4D  ; 83 c9 4d
e133  eax |= 0x1c4; rec->0xac = eax
e14e  rec->0x00 = 0                          ; c7 07 00 00 00 00  ← rev > 0x31 / unknown
e154  eax |= 0x60; rec->0xac = eax
e15d  rec->0xa0 = (ecx & ~0x4d) | 0xc = 0x0C
e138  rec->0xac = eax
e13e  rec->0x64 = rec->0x60 * rec->0x78 * rec->0x80   ; 0f af 57 78 / 0f af 97 80 / 89 57 64
e14c  ret
```

`rec+0x74` is only a copy of `hwInfo+0x18` (write at 0xe02d), not derived from the branch (see table).

Semantics of the branch: the revision thresholds 0x13/0x27/0x31 are the same ranges
`Gfx9Lib::HwlConvertChipFamily` (user space, 0x7d940) uses for `isVega10` (rev−1 < 0x13),
`isVega12` (rev−0x14 < 0x14), `isVega20` (rev−0x28 < 0xD7): the three branches are **Vega10 / Vega12 /
Vega20 dGPU**, and the fallback is "not recognised".

Because Renoir always runs the **Vega10Hardware** class (NootedRed's personality is
`AMDVega10GraphicsAccelerator` and `readChipRevFromRegister` is the Vega10 implementation returning
1 or 2), the branch taken on Renoir is **Vega10**: `family=0x8D, numSE=4, flags=0x4D, workarounds=0xFDF`.

On Renoir the *kernel* tells user space (in `sHardwareInfo`) that there is 1 SE, 1 SH, 8 active
CUs — but the GL driver ignores those and writes the Vega dGPU 4-SE model.

---

## 5. What the correct Renoir/Green Sardine values should be

Facts used: Renoir (0x1638, family 0x8E, gfx9/DCN2) = **1 shader engine, 2 shader arrays (SH), 8 CUs,
2 RB+**; NootedRed's kernel wrapper reports seCount=1, shCount=1, hwMaxCUs=8 →
`sHardwareInfo+0x20 = 8`.

| rec off | Vega10 driver value | Renoir correct | why / confidence |
|---|---|---|---|
| 0x00 family | 0x8D | **0x8D is the pragmatic correct value for this driver build** | The bundled addrlib implements only FAMILY_AI; NootedRed's kernel addrlib wrapper also returns `ADDR_CHIP_FAMILY_AI` for RV. Real RV (0x8E) would require a user-space RV port (isRaven/isDcn1/isDcn2, RV has different pipe config and depth-pipe XOR rules — compare Mesa `HwlConvertChipFamily` FAMILY_RV branch). **high** |
| 0x10 chipRev | 1 or 2 | 1/2 is what the kernel supplies; addrlib then applies `isVega10` settings (metaBaseAlignFix + depthPipeXorDisable, **no** htileAlignFix/applyAliasFix). NootedRed kernel-side for Renoir wants `htileAlignFix = applyAliasFix = metaBaseAlignFix = 1`, so user/kernel addrlib settings differ. Fixing this needs an extra patch in `HwlConvertChipFamily` (see §6-C2). **high** (values), **low** (whether it matters for GL surfaces) |
| 0x20 CUs/SE | 8 (from kernel) | 8 | high |
| 0x60 = 0x20 | 8 | 8 | high |
| 0x74 total RB+ | `hwInfo+0x18` | kernel-supplied; expected 2 for Renoir (RB+ count), must equal `rec+0x78 * numRBperSE` | **medium** — the kernel field itself is only copied, and no writer for `hardware+0x44` was found in the X5000 text; needs a runtime read to confirm what the stock driver reports on Renoir |
| 0x78 numSE | **4** | **1** | high — CU product is used as CL max CUs (32 vs 8), bin-size table and SPI math use `bsr(rec+0x78)` as numSE log2 |
| 0x80 | 1 | 1 | high |
| 0x90/0x84/0x88/0x8c | 0x10/0x20/0x7F/0x1000 | unknown; possibly 8/0x20/0x7F/0x1000 if these are “max CUs per pipe/SE” style caps | low — cannot be derived statically; must be probed/runtime-tested. Do not patch blindly |
| 0xa0 flags | 0x4D | unknown; Vega10 value keeps bit1 clear so RB+/dual-quad packets stay skipped (see §7) | low |
| 0xac flags | arg3\|0xC1 | unknown | low |
| 0xb0 workarounds | 0xFDF | `0xFDF` (Vega-family gfx9 workarounds; probably ASIC-independent) | medium |

Note: on an actual Renoir the kernel would ideally *not* report chipRev 1/2 (Vega10 range) at all; the
"correct" fix in the driver would be a 4th branch (`family == 0x8E` → RV settings + 1 SE), which is
exactly what the maintainer says is missing. The patch set below approximates that by correcting the
values that the Vega10 branch produces, without adding RV code the driver cannot execute.

---

## 6. Patch proposal (15.8.1, exact offsets/bytes)

All offsets are file offsets in
`/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver`.
Pattern uniqueness was checked byte-wise over the whole bundle (§9 command 6).

### A. Primary: shader-engine count (`rec+0x78`), 4 → 1

Site A1 — Vega10 branch (the branch Renoir actually takes):

```
file offset 0xe081
original:  c7 47 78 04 00 00 00      ; movl $4,0x78(%rdi)
patched:   c7 47 78 01 00 00 00      ; movl $1,0x78(%rdi)
find pattern (unique, 7 bytes): C7 47 78 04 00 00 00   (occurrences: 0xe081, 0xe0cc, 0xe109)
```

Site A1 with more context (distinguishes the Vega10 branch unambiguously; 19 bytes starting 0xe07b):

```
C7 07 8D 00 00 00   C7 47 78 04 00 00 00   C5 F8 28 05 50 FE 0D 00
```

Sites A2 (defensive, same 7-byte replacement at 0xe0cc and 0xe109 for the Vega12/Vega20 branches).
Effect: `rec+0x64 = 8 * 1 * 1 = 8` (was 32); `bsr(rec+0x78)` in the bin-table path becomes 0, matching
a 1-SE part; `InitDriverSettings`'s `rec+0x78 >= 3` bit becomes 0. Low risk: only counts change.

### B. Family 0x8D → 0x8E (only together with the addrlib/UBM patches; **not recommended alone**)

```
0xe07b: C7 07 8D 00 00 00 → C7 07 8E 00 00 00      (Vega10 branch; 3 occurrences: 0xe07b/0xe0c6/0xe103)
0x5eeea: C7 43 18 8D 00 00 00 → C7 43 18 8E 00 00 00   (UBM blit HWL struct family; unique)
0x68255: 3D 8D 00 00 00 → 3D 8E 00 00 00           (`Addr::Lib::Create`: accept 0x8E for the gfx9 lib; unique)
0x7d940: 81 FE 8D 00 00 00 → 81 FE 8E 00 00 00      (`Gfx9Lib::HwlConvertChipFamily`: treat 0x8E as Vega)
```

With only these, the user-space addrlib gets `chipFamily=0x8E, chipRevision=1/2`, and
`HwlConvertChipFamily` will now run the **Vega10 case** (`isVega10 = ASICREV_IS_VEGA10_P(rev)` = 1 for
rev 1/2) → settings `isArcticIsland, isVega10, isDce12, metaBaseAlignFix, depthPipeXorDisable`, i.e.
still *not* `isRaven/isDcn1/isDcn2`. So B is cosmetic unless a real RV branch is added (which would
require injecting code; not feasible with page patches). Do not ship B together with A1 without a
plan for the kernel-side alignment (see §6-C2/§8).

### C. Optional addrlib alignment patches (user-space addrlib vs NootedRed's kernel addrlib for Renoir)

NootedRed's kernel `wrapHwlConvertChipFamily` sets for Renoir: `isArcticIsland=1, isRaven=1,
isDcn1=1, metaBaseAlignFix=1, htileAlignFix=1, applyAliasFix=1` (no depthPipeXorDisable). The GL
driver's AI branch can at best produce `isArcticIsland=1, metaBaseAlignFix, depthPipeXorDisable,
htileAlignFix, applyAliasFix` (for rev in Vega12/20 range, dword2 = 0xF) — it can never set
isRaven/isDcn1/isDcn2.

* C1 (cheap, forces htile/alias fixes for rev 1/2): at 0x7d999 `BE 03 00 00 00` (`movl $3,%esi`,
  used as the `cmovb` source for settings dword2) → `BE 0F 00 00 00` (`movl $0xf,%esi`). Then
  `settings.dword2 = 0xF` (metaBaseAlignFix+depthPipeXorDisable+htileAlignFix+applyAliasFix) for the
  AI/rev-1..0x13 case. Side effect: `depthPipeXorDisable` becomes 1, which NootedRed's kernel does
  *not* set for Renoir—so this only reduces (not removes) the user/kernel divergence. Verify against
  the kernel addrlib empirically before enabling.
* C2 (proper): a real RV branch would have to be code-injected; out of scope for a page patch.

### D. Blend-related candidate patches (hypotheses; test only, see §7/§8)

* D1 — force CB dual-quad state path: in `_glrAMD_GFX9_UpdateHwCbDualQuadMode` the flag is only
  computed when `ctx+0x30ec` bit2 (dual-source blend active) is set:
  ```
  0x813f: F6 87 EC 30 00 00 04   testb $0x4,0x30ec(%rdi)
  0x8146: 74 12                   je 0x815a        ← patch to 90 90
  ```
  Then `ecx = (rec+0xa0>>1)&1` is always used and written to `CB_COLOR_CONTROL` (reg 0x202, packet
  `0x202C0016900`) through ctx+0x1398 bit0. This is the 15.8.1 analogue of the community fork's
  "force DISABLE_DUAL_QUAD for iGPU" patch (`74 28 → 90 90`, macOS 26 build), but note the sign of
  the effect is inverted relative to the current binary: today bit0 = 0 because `rec+0xA0` bit1 is
  clear in the Vega10 branch. Test both directions (see §8).
* D2 — `rec+0xA0` flags: 0x4D→0x4C at 0xe0a2 (and 0xe12a) clears bit2, not bit1; use only if §8 shows
  flags matter. `83 C9 4D` occurs at 0xe0a2 and 0xe12a (2 hits); `83 C9 4F` at 0xe0ed (1 hit).
* Do **not** patch the `je 0xe0b5` (0xe06d) to force the "no family" path: it sets family 0, which
  `Addr::Lib::Create` rejects and disables the CU product entirely.

### E. Application notes (for `NootedRed/UserPatches`)

* All sites are in `__TEXT:__text`; the user-space page patcher needs whole 4 KiB page images that are
  byte-identical to the 15.8.1 file: page bases are `0xE000` (A1/A2/D1/D2), `0x68000` (B/AddrCreate),
  `0x7D000` (B/HwlConvertChipFamily), `0x5E000` (B/UBM). Extract with
  `xxd -s 0xE000 -l 4096` etc.; apply the byte replacements above inside the image.
* Version-gate with `currentKernelVersion() == MACOS_15_X` (`>= MACOS_15 && < MACOS_16` if a constant
  exists) and fail closed when the page image does not match, as `analysis/lilu-userpatch.md` already
  prescribes. Do not reuse these offsets on 15.0–15.7 without re-verifying the pages; the pattern
  strings (`C7 47 78 04 00 00 00` inside `_gfx9_HwInfoInitData`) are the more robust anchor.
* Kernel-side equivalent does **not** exist for this bug: the driver is user-space, and the kernel
  `sHardwareInfo` is already "correct" for Renoir thanks to NootedRed's wraps. No NootedRed kernel
  patch can reach `_gfx9_HwInfoInitData`.

---

## 7. Reachability: can this function explain blend-specific corruption?

Verified reachability and dataflow:

* Called exactly twice in the bundle: once per share-group init (0x1640) and once per compute-device
  init (0x1d07e). It runs before any GL state programming, once per context/device.
* Its output is consumed by the **pipeline setup** (`_glrAMD_GFX9_InitDriverSettings`,
  `_glrAMD_GFX9_AddrLibInit`), the **compute config**, and — via `rec+0xa0` — by the RB+ state
  functions: `UpdateHwBlendOptState` (SX_BLEND_OPT_CONTROL 0x1D7), `UpdateHwSxBlendOptState`
  (settings bit19 derived from `rec+0xa0` bit1), `UpdateHwExportBlockState`,
  `UpdateHwDrawBufferRegs`, `UpdateHwCbDualQuadMode` (CB_COLOR_CONTROL 0x202),
  `WriteAllHwContextRegs`.
* **Therefore yes, the function is on the blend path** — but in this 15.8.1 build all those
  `testb $0x2, rec+0xa0` gates evaluate **false** for the Vega10 branch value 0x4D (bit1 clear);
  only the Vega12 branch (0x4F) sets it. So if Renoir takes the Vega10 branch, the RB+ blend
  optimisation packets are *already* not programmed and the remaining damage is:
  1. `rec+0x64`/`rec+0x78` (4× too many CUs, 4 SE instead of 1) — affects context/ring setup
     (`ValidateShaderRings`), SPI late-alloc wave math, binning tables, compute config;
  2. the addrlib chip configuration (AI/Vega10 instead of RV) — affects surface tiling/meta
     alignment, i.e. how every texture/render-target is laid out. A tiling mismatch between the GL
     driver's surfaces and what the RB/DB expects would corrupt rendered output exactly where
     blending/ROP reads+replaces destination pixels (blend reads the destination!).
* If, contrary to the above, the device layer leaves the family code at 0, the driver would take the
  no-family path (family 0 → AddrCreate error). That would break GL init, not corrupt output, so it
  is *not* the observed state (Chromium renders corrupted, it does not lose GL entirely).
* The community fork's LegacyBlend patch (macOS 26, `74 28 → 90 90`) targets the
  `UpdateHwCbDualQuadMode`-equivalent gate, which suggests that on newer builds the dual-quad bit is
  wrongly enabled for iGPU. On 15.8.1 that gate is currently *not* taken (bit0 = 0); patch D1 changes
  that only if the dual-source flag is set, so it is a diagnostic experiment, not a confirmed fix.

Bottom line: **the count/family mis-modelling is reachable and affects every blend draw; the RB+/dual
quad packets are already disabled on this build.** The most defensible single change is A1
(numSE 4→1).

---

## 8. Confidence, side effects, alternatives, open questions

| item | confidence | notes |
|---|---|---|
| sHardwareInfo = kernel copy at hardware+0xd0, 0x204 bytes, `getHWInfo` = vtable 0x1c0 | **high** | getter disasm + memcpy + klog format strings |
| arg3 = `(dev+0x2e8) & 0xFFF0000`; descriptor packing (devID/family/rev) | **high** for the mask/packing; **medium** for which family code Renoir gets at runtime |
| rec field map (§3 layout, offsets, sources) | **high** | every write traced; size 0xb4 confirmed by `malloc(0xb4)` and `rec+0xb0` workarounds |
| rec+0x64 = total CU count = `rec+0x60*rec+0x78*rec+0x80` | **high** | used for CL max CUs and ring validation |
| rec+0x78 = number of SEs | **medium-high** | product + `bsr` usage + bin-table indexing; both `numSE` and `numRbPerSe` interpretations fit for Vega10 (4/4 ambiguity), product favours numSE |
| Renoir takes the Vega10 branch (rev 1/2) | **high** | Vega10Hardware class + readChipRevFromRegister returns 1/2 |
| "RB+ blend-opt” packets already off for Vega10 flags 0x4D | **high** (code), **medium** (semantics of flag bit1) |
| A1 patch (4→1) fixes CU count and is low risk | **medium-high** | deterministic; may reveal follow-on errors (pipe mismatch) on real HW |
| setting family 0x8E fixes the bug | **low** | addrlib has no RV support; would need B+C and still lacks isRaven/isDcn1/isDcn2 |

Side effects of A1: none kernel-side, user-space only, per-page COW if implemented like the fork
(process-local); the driver may program a 1-SE pipe config where it previously assumed 4 SEs — if any
other hard-coded assumption (e.g. `rec+0x90`, `rec+0x74`, bin tables) is still dGPU-shaped, output
may change but should move towards the real hardware. Test with the existing `tools/gl_blend_probe`
(`--render` after Lead approval) and the `.gpuRestart` / corruption rate as the metric.

Alternatives (ranked):
1. A1 (+A2) — fix the counts, keep AI family. Minimal, reversible, testable.
2. A1 + C1 — additionally align user-space addrlib fixes with NootedRed's kernel addrlib
   (htileAlignFix/applyAliasFix). Slightly higher risk of layout divergence in the other direction;
   needs a surface-layout comparison or a controlled test.
3. D1 (`je`→`nop` in CbDualQuadMode) — targeted RB+ dual-quad experiment for blend corruption;
   keep as a separate toggle so its effect is measurable.
4. B+C — full RV family emulation. Only with a real RV port in user-space addrlib; otherwise
   “half-RV” settings are more dangerous than strict AI emulation.

Open questions that need runtime data (no GPU stress needed for most):
* Read `rec` after share-group init on Renoir (e.g. an `--inspect`-mode hook or lldb on the GL
  process right after `_glrInitializeShareGroup`): confirm `arg3`, `rec+0x00`, `rec+0x10`, `rec+0x74`,
  `rec+0x78`, `rec+0x64`, `rec+0xa0`, `rec+0xb0`. This single snapshot resolves the family/arg3
  question and the true `numRasterPipe` value.
* Read back `CB_COLOR_CONTROL` (reg 0x202) and `SX_BLEND_OPT_CONTROL` (0x1D7) in `glblend*.app` and
  compare Vega-assumed vs Renoir-correct programming.
* Check `GL_MAX_COMPUTE_UNITS` / `GL_MAX_COMPUTE_WORK_GROUP_COUNT` before/after A1 — should change
  from 32 to 8 (CL config path uses the same value) — a cheap user-space verification without drawing.

---

## 9. Reproduction commands

```sh
B=/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver

# 1) whole function
objdump -d --start-address=0xdf40 --stop-address=0xe168 "$B"
# 2) verify file offset == vmaddr
xxd -s 0xdf40 -l 8 "$B"            # 55 48 89 e5 89 d0 8b 8f
# 3) branch / constants (also shows the xmm constants {1,0x20,0x7f/0x80,0x1000})
xxd -s 0xe060 -l 0x108 "$B"
xxd -s 0xeded0 -l 32 "$B"
# 4) callers
objdump -d --start-address=0x1576 --stop-address=0x1700 "$B"     # glrInitializeShareGroup
objdump -d --start-address=0x1cf8f --stop-address=0x1d12f "$B"   # glrAMD_GFX9_InitComputeDevice
objdump -d --start-address=0x48ed8 --stop-address=0x49574 "$B"   # glrInitializeDevice (arg3 packing)
objdump -d --start-address=0x5ee3a --stop-address=0x5ef30 "$B"   # amdUbm_HWL_Init
objdump -d --start-address=0x58684 --stop-address=0x586a7 "$B"   # gfx9_HwWorkAroundsInitFlags
objdump -d --start-address=0x60098 --stop-address=0x600eb "$B"   # InitDriverSettings
objdump -d --start-address=0x7f62  --stop-address=0x8037  "$B"   # UpdateHwBlendOptState
objdump -d --start-address=0x8134  --stop-address=0x81c2  "$B"   # UpdateHwCbDualQuadMode
objdump -d --start-address=0x81c2  --stop-address=0x8370  "$B"   # UpdateHwSxBlendOptState
objdump -d --start-address=0x1d12f --stop-address=0x1d369 "$B"   # GetDeviceComputeConfig (CU count)
# 5) kernel side
nm -n /tmp/X5000.kext.macho | grep -E "getHardwareInfo|initHWInfo|setupAndInitializeHWCapabilities"
objdump -d --start-address=0x4364dde --stop-address=0x4364fb2 /tmp/X5000.kext.macho   # getHardwareInfo
objdump -d --start-address=0x43cba44 --stop-address=0x43cbcc0 /tmp/X5000.kext.macho   # AMDHardware::initHWInfo
objdump -d --start-address=0x43c6e8c --stop-address=0x43c6e99 /tmp/X5000.kext.macho   # getHWInfo getter
objdump -d --start-address=0x43c9226 --stop-address=0x43c98d2 /tmp/X5000.kext.macho   # AMDHardware::init (devID/rev)
objdump -d --start-address=0x43ba3d8 --stop-address=0x43ba60c /tmp/X5000.kext.macho   # GFX9 caps/SE-SH-CU
# 6) verify patch-pattern uniqueness (run from the workspace; python3)
python3 - "$B" <<'PY'
import sys
d=open(sys.argv[1],'rb').read()
for name,hexpat in {
 "numSE=4 (A1/A2)": "c7477804000000",
 "family=0x8d (B)": "c7078d000000",
 "AddrCreate 0x8d": "3d8d000000",
 "HwlConvertChipFamily 0x8d": "81fe8d000000",
 "UBM family 0x8d": "c743188d000000",
 "orl 0x4d (D2)": "83c94d",
 "orl 0x4f": "83c94f",
 "CbDualQuad je (D1)": "f687ec300000047412",
}.items():
    p=bytes.fromhex(hexpat); i=0; hits=[]
    while True:
        j=d.find(p,i)
        if j<0: break
        hits.append(hex(j)); i=j+1
    print(name, hexpat, hits)
PY
```

Expected output for 15.8.1 (recorded): `numSE=4` → `['0xe081','0xe0cc','0xe109']`; `family=0x8d` →
`['0xe07b','0xe0c6','0xe103']`; `AddrCreate 0x8d` → `['0x68255']`; `HwlConvertChipFamily` →
`['0x7d940']`; `UBM family` → `['0x5eeea']`; `orl 0x4d` → `['0xe0a2','0xe12a']`; `orl 0x4f` →
`['0xe0ed']`.
