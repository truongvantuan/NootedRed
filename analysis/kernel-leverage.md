# Kernel-side leverage for issue #158 — provenance and reachability of the GL driver's HwInfo inputs

Status: static analysis only. Nothing here was executed on the GPU; the NootedRed kext was not
modified. Target environment: macOS 15.8.1 (24H32, Darwin 24.6.0, x86_64), NootedRed `master`
(worktree HEAD `9ff85a6`), Renoir/Green Sardine iGPU 0x1638.

Artifacts used:

- `/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver`
  (Mach-O x86_64h, 1,808,640 bytes, driver 7.0.25). For this bundle file offset == vmaddr.
- `/tmp/X5000.kext.macho` + `/tmp/HWLibs.kext.macho` (extracted from `/tmp/sys.kc`, symbol tables
  usable), `/tmp/sys.kc` (kernel collection), `/tmp/x5000gl.dis` (full GLD disassembly).
- `/tmp/gld.fixups` (`dyld_info -fixups` of the GLD) for import/stub resolution.

Companion files from the rest of the investigation: `analysis/gl-hwinfo.md` (exhaustive user-space
`_gfx9_HwInfoInitData` RE and patch candidates), `analysis/lilu-userpatch.md`, `analysis/repro-plan.md`.
This file deliberately focuses on **what the kernel can and cannot reach**.

---

## 0. TL;DR / verdict

| Question | Answer |
| --- | --- |
| What is the 0x204-byte `_sAMD_GET_HW_INFO_VALUES` (arg2) the GL driver feeds to `_gfx9_HwInfoInitData`? | A byte-for-byte `memcpy` of the **kernel `AMDHWInfo`** (`sHardwareInfo`, 0x204 bytes) served by `AMDRadeonX5000_AMDAccelDevice::getHardwareInfo` through IOConnect selector `0x100`. Proven. |
| Does it originate from kernel `AMDHWInfo` / `GB_ADDR_CONFIG` / IOAccel shared memory / PCI config? | Kernel `AMDHWInfo`. Inside it: `GB_ADDR_CONFIG` comes from MMIO (GC reg `0x63E` = `mmGB_ADDR_CONFIG`), device ID/revision from PCI config, CU masks/VRAM clocks from the MCIL/ATOM register-read service, CU count computed in `setupAndInitializeHWCapabilities`. IOAccel shared memory is **not** involved for this struct. Proven enough for the listed fields. |
| Can NootedRed control all fields of arg2 from kernel space? | **Yes, technically** — hook `AMDAccelDevice::getHardwareInfo` and rewrite the 0x204 bytes before user space copies them. NootedRed does not currently hook it, and it already feeds several of these fields correctly via `wrapSetupAndInitializeHWCapabilities`. |
| Is arg3 (`*(ctx+8+0x2e8) & 0xFFF0000`) kernel-controllable? | **Not through AMDAccelDevice/AMDHWInfo hooks.** `+0x2e8` is never written by any code in the GLD; it is filled by the generic libGPUSupportMercury/IOAccel device-creation path (packed `{u16 deviceID, bits[18:16] = Vega class, bits[31:28] = variant}`). Reaching it would require patching IOAcceleratorFamily2 or libGPUSupportMercury's data source, which is unproven and outside NootedRed's current target set. |
| Can a kernel-only patch fix #158? | **No.** The specific defects the maintainer points at are literals/branches in the *user-space* driver: `_gfx9_HwInfoInitData` hardcodes chip family `0x8D` (AI/Vega10) into its output record and hardcodes Vega SE/RB/CU presets (e.g. `rec+0x78 = 4` ⇒ CU product 32 instead of Renoir's 8), and `_amdUbm_HWL_Init` hardcodes `0x8D` too. The user-space AddrLib consuming those records accepts only family 0x8D/0x8F. No kernel field carries a chip family, and no kernel value can change those literals. Kernel can only make the *inputs* truthful — which they mostly already are. |
| Most useful kernel-side actions | The team's interposer already measured `arg3 = 0x00010000` (⇒ Vega-dGPU branch; `analysis/lead-findings.md`), so the remaining decisive check is whether `arg2[0xa0]` (the kernel `GB_ADDR_CONFIG`) agrees with that class descriptor. NootedRed's `GoldenSettings.hpp` programs Renoir with the **Raven** value `0x24000042` (tile-size bits 0), while Linux Renoir uses `(read & 0xF3E777FF) OR 0x22010042` (tile-size bits 1); a one-line read-only log answers this. If they disagree, that mismatch is a concrete kernel-side defect candidate; if they agree, the kernel side has no useful contribution left and the user-space A1 patch is the whole fix. |
| Navi leftover in `X6000FB` | Real but **display/FB-side** (`AmdRadeonControllerNavi10` personality). It can cause separate display/VRAM/power issues but does not program CB/SX blend state; it is not a plausible standalone fix for #158. Details in §5. |
| Recommended priority | **User-space patch first** (only root fix). Kernel-side: correctness/hygiene + instrumentation; treat the `GB_ADDR_CONFIG` golden audit as a testable side-quest, not the main fix. Risks in §6. |

---

## 1. The user-space call chain (what feeds what)

`_glrInitializeShareGroup` @ GLD `0x1576` (also `_glrAMD_GFX9_InitComputeDevice` @ `0x1cf8f` and
`_amdUbm_HWL_Init` @ `0x5ee3a` do the same thing):

```
rbx = sharegroup                    ; argument 1 of glrInitializeShareGroup
rax = *(sharegroup + 8)             ; gpus "device" object (libGPUSupportMercury-owned)
rdi = *(device + 0x230)             ; IOAccelDeviceRef
call IOAccelDeviceGetConnect        ; GLD import stub 0xecf0a -> IOAccelerator/_IOAccelDeviceGetConnect
edi = returned io_connect_t         ; connection to the AMDAccelDevice user client
IOConnectCallMethod(connect, selector=0x100,
                    input=NULL, inputCnt=0, inputStruct=NULL, inputStructCnt=0,
                    output=NULL, outputCnt=NULL,
                    outputStruct=local_0x204_buffer, outputStructCnt=&0x204)
call _gfx9_HwInfoInitData(sharegroup + 0x168 /*0xb4-out*/,
                          local_0x204_buffer,
                          *(device + 0x2e8) & 0xFFF0000)
call _gfx9_HwWorkAroundsInitFlags(sharegroup + 0x218, same arg3, sharegroup + 0x178/*rec+0x10*/)
call _glrAMD_GFX9_InitDriverSettings(sharegroup + 0x168 /*rec*/, sharegroup + 0x21c /*settings*/)
call _glrAMD_GFX9_AddrLibInit(sharegroup + 0x228, sharegroup)
call _glrAMD_GFX9_SCInit(sharegroup + 0x230, sharegroup + 0x168)
```

Evidence (all addresses are GLD vmaddrs, matched against `/tmp/x5000gl.dis`):

- `0x15df–0x15ed`: `movq 0x8(%rbx),%rax; movq 0x230(%rax),%rdi; callq 0xecf0a` — `0xecf0a` is the
  lazy stub that `dyld_info -fixups` binds to `IOAccelerator/_IOAccelDeviceGetConnect`
  (`__got 0x14d188`).
- `0x15f2–0x1621`: the 10-argument `IOConnectCallMethod` call (`0xecf64` → `IOKit/_IOConnectCallMethod`),
  `esi = 0x100`, output struct = 0x204 bytes.
- `0x1626–0x1640`: `andl 0x2e8(%rax),%r13d` with mask `0xFFF0000`; `callq 0xdf40`
  (`_gfx9_HwInfoInitData`) with `rdi = sharegroup+0x168`, `rsi = 0x204 buffer`, `edx = arg3`.
- Secondary consumers of the *same* struct: `_amdUbm_HWL_Init` (0x5ee3a) repeats
  `IOAccelDeviceGetConnect` + selector `0x100` into its own 0x204 stack buffer, then projects it into
  the blit/UBM HWL struct with **family 0x8D hardcoded** at `ubm+0x18` (see `analysis/gl-hwinfo.md`).

Note on naming: in the brief's notation `ctx` is the object passed to `_glrInitializeShareGroup` — i.e.
the gpus **share-group** object. `ctx->8` is the gpus **device** object (created by
libGPUSupportMercury). The two fields the brief asks about are on the device object:
`(ctx->8)+0x230` = IOAccelDeviceRef and `(ctx->8)+0x2e8` = packed GPU descriptor (arg3).

---

## 2. Provenance of arg2 — it is the kernel `AMDHWInfo`

### 2.1 Kernel selector 0x100 = `AMDAccelDevice::getHardwareInfo`

The X5000 kext symbol table (from `/tmp/X5000.kext.macho`, identical to `/tmp/sys.kc`):

```
0000000004364d5e T AMDRadeonX5000_AMDAccelDevice::deviceStart()
0000000004364d86 T AMDRadeonX5000_AMDAccelDevice::deviceStop()
0000000004364d98 T AMDRadeonX5000_AMDAccelDevice::getTargetAndMethodForIndex(IOService**, unsigned int)
0000000004364dde T AMDRadeonX5000_AMDAccelDevice::getHardwareInfo(_sAMD_GET_HW_INFO_VALUES*)
0000000004364fb2 T AMDRadeonX5000_AMDAccelDevice::getCpuGpuTimes(sAMD_CPU_GPU_TIMES*)
```

`getTargetAndMethodForIndex` (`0x4364d98`) dispatches selectors 0x100/0x101 through a vendor table
based at `0x457b750` with 0x30-byte entries (`rax = 3*sel; shl 4; lea 0x457e750; add; add -0x3000`).
Selector 0x100's slot is at `0x457e750` and contains the function address `0x4364dde` plus an
output-structure size field of `0x204` (the only occurrence of that pointer encoding in the kext;
file offset `0x227758`, vaddr `0x457e758`). Selector 0x101's slot at `0x457e780` points at
`0x4364fb2` (`getCpuGpuTimes`) with size `0x10`, which independently confirms the table layout.

### 2.2 What `getHardwareInfo` does

Disassembly of `0x4364dde` (`objdump -d --start-address=0x4364dde --stop-address=0x4364fb2`):

```asm
movq 0x108(%rdi),%r15       ; accelerator (IOGraphicsAccelerator2 provider)
leaq 0x90(%r15),%r12        ; IOLock
...  IOLockLock/IOLockUnlock around the copy
movq 0x1a38(%r15),%rdi      ; IAMDHWInterface implementation object (= AMDHardware)
movq (%rdi),%rax
callq *0x1c0(%rax)          ; vtable slot 0x1C0 == getHWInfo() -> &sHardwareInfo
movl $0x204,%edx
movq %r14,%rdi              ; user-supplied _sAMD_GET_HW_INFO_VALUES*
movq %rax,%rsi
callq memcpy                ; out = sHardwareInfo[0x204]
; then validates two canary groups: out[0xc0..0xd8] != 0 and out[0x00]/out[0x18]/out[0x20] != 0
; on failure it logs through AMDAccelDevice::gMetaClass and returns kIOReturnError.
```

The vtable slot `+0x1C0` is the same offset NootedRed already documents for
`AMDRadeonX5000_AMDHWInterface::getHWInfo()` on macOS ≥ 11 (`NootedRed/GPUDriversAMD/Accel/HWInterface.hpp`
lines 40–51). In this 15.8.1 build the resolved target is the tiny getter at `0x43c6e8c`:
`lea 0xd0(%rdi),%rax; ret` — i.e. **`sHardwareInfo` is the 0x204-byte struct embedded at
`AMDHardware + 0xd0`**. (`AMDHardware::initHWInfo` @ `0x43cba44` does `memset(this+0xd0, 0, 0x204)` at
`0x43cba7b`, then fills it.)

**Conclusion (high confidence): arg2 is exactly `AMDHWInfo`, no translation, no masking, no IOAccel
shared memory.** The GL driver consumes it in `_gfx9_HwInfoInitData` (and UBM) and projects it into its
own 0xb4-byte `GFX9_HwInfoRec`.

### 2.3 Who fills `AMDHWInfo` (kernel side)

`AMDHardware::initHWInfo` @ `0x43cba44`, `AMDGFX9Hardware::initHWInfo` @ `0x43ba716`,
`AMDHardware::init` @ `0x43c9226`, `AMDGFX9Hardware::setupAndInitializeHWCapabilities` @ `0x43ba3d8`.
Field map (B = `AMDHardware+0xd0`; "GLD reads" column = offset read by `_gfx9_HwInfoInitData` @
`0xdf40`):

| HWInfo off | Written from | Meaning (best evidence) | GLD reads |
| --- | --- | --- | --- |
| +0x00 | `movq [this+0x2fc]` (PCI config u16s copied in `AMDHardware::init`) | `u16 deviceID` + vendor/subsystem u16s; validated by `getHardwareInfo` | `movzwl (%rsi)` → rec+0x0c |
| +0x08 | `this+0x2f8` = `readChipRevFromRegister()` (vtable `*0x6a8`) | chip revision/family class (Vega10Hardware class returns 1 or 2) | `movl 8(%rsi)` → rec+0x10; also branch selector `cmpl 0x13/0x27/0x31` |
| +0x10 | `[this+0x18]->vt+0x1c0()` (u32) | HW-handler/accelerator value | — |
| +0x18 | `this+0x44` | raster pipe count | `movl 0x18` → rec+0x74 |
| +0x20 | `this+0xa4` = `min(ΣCU masks, this+0xa0 hwMaxCUs)` | **total CUs** (8 on Renoir because NootedRed sets hwMaxCUs=8) | `movl 0x20` → rec+0x60 |
| +0x28..+0x40 | `this+0xf8/0x100/0x108/0x110` ← `this+0x70/0x78/0x80/0x88` (MCIL SH table copies) | CU enable masks | `movl 0x28/0x30/0x38/0x40` → rec+0x40..0x4c; `tzcntl 0x28` → rec+0x9c |
| +0x88 / +0x90 | `this+0x158/0x160` ← `this+0x64/0x6c` | seCount / shCount (NootedRed sets both to 1) | — |
| +0xa0 | `this+0x170` ← `this+0x48` = GC MMIO reg `0x63E` | **`GB_ADDR_CONFIG`** | `movl 0xa0(%rsi)` → rec+0xa4 (forwarded to user AddrLib as addrConfig) |
| +0xa8 | `this+0x178` ← `this+0x4c` | second GC caps dword | — |
| +0xc0..+0xd8 | `this+0x190/0x198/0x1a0/0x1a8` (ATOM/MCIL clock table #4, u64s) | refClk/sysClk/memClk/cgRefClk (GLD divides by 100 → MHz) | `u64 /100` → rec+0x1c..0x28 |
| +0xe0 | `this+0x1b0` ← `[this+0x378]->vt+0x1d0()` | VRAM-ish u64 | `>>0x14` → rec+0x14 |
| +0xe8 / +0xec | `this+0x1b8/0x1bc` (ATOM table #8) | u32s | rec+0x18 |
| +0xf0..+0x110 | `this+0x1c0..0x1e0` = `[this->vt+0x310(k)]->vt+0x190(i)` | queue/engine info from HW objects | rec+0x2c..0x3c |
| +0x1f0.. | `this+0x2c0/0x2c4` (ATOM #6 / PCI config) | misc | — |

Sources of the values: (a) **MMIO**: GC `0x63E` (`mmGB_ADDR_CONFIG`, gfx9 `gc_9_0_offset.h`),
`0x63F`, and `0xD4/0xD5` via `AMDHWRegisters::read` (vtable `+0x118`); (b) **PCI config** through
`AMDHardware::init`'s `configRead16` quadruple and MCIL `GetPciConfigData`; (c) **MCIL/ATOM service**
(register-read command `3`/`5`/`6`/`8` through `this+0x340` vtable `+0x50`) for clocks, VRAM sizing,
CU mask tables, engine counts; (d) **computed** in `setupAndInitializeHWCapabilities` (CU totals from
the mask tables intersected with `hwMaxCUs`).

No IOAccel shared-memory read is involved. NootedRed's existing hooks already modify inputs to (d)
(`seCount`, `shCount`, `hwMaxCUs` in `X5000::wrapSetupAndInitializeHWCapabilities`), and the user-space
side sees the results in arg2 (e.g. HWInfo+0x20 = 8 on Renoir).

### 2.4 How user space consumes arg2 (why kernel input matters)

`_gfx9_HwInfoInitData(rec, hwInfo, arg3)` @ `0xdf40` writes a 0xb4 record at `sharegroup+0x168`:

- `rec+0x0c = hwInfo+0x00` (deviceID), `rec+0x10 = hwInfo+0x08` (revision),
  `rec+0x60 = hwInfo+0x20` (CU count), `rec+0x40..0x4c = hwInfo+0x28..0x40` (CU masks),
  `rec+0xa4 = hwInfo+0xa0` (**`GB_ADDR_CONFIG`**), `rec+0x2c..0x3c = hwInfo+0xf0..0x110`.
- then `testl $0x70000, arg3` (: `addrConfig & SHADER_ENGINE_TILE_SIZE_MASK`). If non-zero it takes
  the Vega path and writes **literals**: `rec+0x00 = 0x8D` (family AI),
  `rec+0x78 = 4` (shader engines), preset masks at `rec+0x80/0x84/0x90` and flag bits at
  `rec+0xa0/0xac`, selecting one of three presets by `hwInfo+0x08` (`cmpl 0x13/0x27/0x31`). If zero it
  clears `rec+0xa0` bit 6 and leaves `rec+0x00 = 0`.
- `rec+0x64 = rec+0x60 * rec+0x78 * rec+0x80` — this becomes the OpenCL/GL "max compute units".

The literals are the blocker: on Renoir the kernel feeds `rec+0x60 = 8` (correct) but the function
multiplies it by `rec+0x78 = 4`, giving `0x64 = 32`; and `rec+0x00 = 0x8D` makes the *user-space*
AddrLib use Vega10 settings. `analysis/gl-hwinfo.md` §4–§6 has the full write map and the concrete
patch candidates; this section only establishes that **those values are not kernel-reachable**.

**Team runtime corroboration.** After the static work above, the rest of the investigation
instrumented the live driver (`analysis/lead-findings.md`, interposer `GLHOOK_MODE=hwinfo`): on Renoir
0x1638, `_gfx9_HwInfoInitData` is called with `arg3 = 0x00010000` (bit 16 = SHADER_ENGINE_TILE_SIZE[0]),
i.e. the Vega-dGPU branch *is* taken, and the resulting record contains `family = 0x8d`,
`totalNumComputeUnits = 0x20` (32), `numShaderEngines = 4`, `reserved = 0x4d`, `chip = 0xc1`. That
matches the static projection here exactly (and `reserved = 0x4d` has bit 1 clear, so the RB+ blend-opt
gate discussed in §4.1 is *off* on Renoir already). It also proves that the "Vega class" bits in arg3
come from a Renoir-like addr-config value (tile size 1), not from NootedRed's Raven-valued golden
setting (tile size 0) — see the audit below.

---

## 3. `ctx->8`, `+0x230`, `+0x2e8` (arg3)

### 3.1 `ctx->8` and `+0x230`

The share-group object's `+0x8` is the gpus **device** object created by libGPUSupportMercury
(`gpumCreateDevice` is called from `_gldCreateDevice` @ GLD `0x2357d` with the vendor dispatch table
`_gpus_io_data` @ `0x1559f8` and the `_glrPopulateDeviceConfig` callback @ `0x4957e`). The device's
`+0x230` field is the `IOAccelDeviceRef` obtained from IOAccelerator.framework; `IOAccelDeviceGetConnect`
turns it into an `io_connect_t` for the AMDAccelDevice user client. This is a user-space opaque handle,
not data; the kernel cannot and need not change it. (NootedRed has no visibility into this field.)

### 3.2 `+0x2e8` — packed GPU descriptor

Facts:

1. **No code in the GLD writes it.** An exhaustive scan of the whole 1.8 MB `__text` for stores to
   displacement `0x2e8` finds only unrelated objects (UBM/SC/register-state structs); the only reads of
   the device field are `0x1630` (`_glrInitializeShareGroup`) and `0x1d067`
   (`_glrAMD_GFX9_InitComputeDevice`). `_glrInitializeDevice` reads it at function entry (`0x48eef`),
   *before* issuing any IOKit call of its own.
2. Therefore it is filled during gpus device creation by **libGPUSupportMercury / IOAccel**, from
   kernel-provided device data — the generic IOAccel device path (IOAccelDevice2 user client and/or the
   IOAccel shared page mapped by libGPUSupportMercury), **not** from `AMDAccelDevice::getHardwareInfo`.
3. Packed layout (cross-checked with `analysis/gl-hwinfo.md` §2.4):
   - bits `[15:0]` = PCI device ID (`movzwl %ax,%ecx` then compared against Vega IDs 0x6860/0x687F/0x66AF…),
   - bits `[18:16]` = Vega-class selector (`0x10000`→Vega10, `0x20000`→Vega12, `0x40000`→Vega20),
   - bits `[31:28]` = ASIC variant index used for renderer-string selection,
   - the remaining bits are consumed by `_gfx9_HwInfoInitData` only via `& 0xFFF0000`.
4. Consistency check: bits `[18:16]` are exactly `GB_ADDR_CONFIG.SHADER_ENGINE_TILE_SIZE`
   (gfx9 `GC_9_0_SH_MASK`: mask `0x70000`). So `device+0x2e8` looks like a gpus-level copy of the same
   `GB_ADDR_CONFIG`-derived "Vega class" information. Whether it is literally copied from the kernel
   `AMDHWInfo+0xa0` by the gpus layer could not be proven from the available artifacts
   (libGPUSupportMercury lives in the dyld shared cache; IOAccelDevice2's generic
   `get_device_info`/`get_config` structs do not obviously contain it).

Reachability consequence: even if `+0x2e8` is ultimately kernel-derived, it is **not reachable through
AMDRadeonX5000 code** — NootedRed would have to patch IOAcceleratorFamily2 / libGPUSupportMercury's data
source, which is a new target with no proven field. Treat arg3 as effectively fixed for a kernel-only
patch. (GLD's own patch path does not need it either; see `analysis/gl-hwinfo.md`.)

---

## 4. Kernel leverage: exact recipe, values, version gating

### 4.1 Reachable vs unreachable (summary)

Reachable by patching the X5000 kext:

- Every byte of arg2 (`AMDHWInfo`), including device ID, revision, `GB_ADDR_CONFIG`, CU count, CU enable
  masks, seCount/shCount copies, clock/VRAM/engine fields.
- The kernel-side computations that fill them (`setupAndInitializeHWCapabilities`,
  `initHWInfo`, PCI-config reads, ACPI/ATOM tables, golden settings).

Not reachable from the kernel side as NootedRed is structured today:

- The **chip family literal** `0x8D` in `_gfx9_HwInfoInitData` and `_amdUbm_HWL_Init`, and the
  Vega SE/RB/CU preset literals (`rec+0x78 = 4`, `rec+0x80/0x84/0x90`, flag bits `rec+0xa0/0xac`).
  There is no family field in `AMDHWInfo`; the GL driver never asks the kernel "what family are you".
- The user-space AddrLib family check (`Addr::Lib::Create` @ `0x681a0` accepts only 0x8D/0x8F for
  Gfx9/Gfx10 clients; user `Gfx9Lib::HwlConvertChipFamily` @ `0x7d940` only implements `ADDR_CHIP_FAMILY_AI`).
- The `device+0x2e8` packed descriptor (§3.2).
- Any of the blend/pipe-info **decision logic** in the GLD: `_glrAMD_Hwl_CreatePipeInfo` @ `0x31b1`,
  `_glrAMD_GFX9_UpdateHwBlendOptState` @ `0x7f62`, `_glrAMD_GFX9_UpdateHwSxBlendOptState` @ `0x81c2`,
  etc. They read the records built above; changing their inputs can select a different pre-existing
  branch, but cannot invent the branch the driver lacks.

Two important nuances:

- **The "RB+ blend optimisation gate" is NOT driven by kernel data in this build.** `_glrAMD_GFX9_InitDriverSettings`
  @ `0x60098` derives the share-group settings word (`sharegroup+0x21c`) from `rec+0xa0` — the **branch
  flags literal** written by `_gfx9_HwInfoInitData` (`0x4D` for Vega10/Vega20, `0x4F` for Vega12), not
  from the kernel `GB_ADDR_CONFIG` (which lands at `rec+0xa4`). Bit 19 of settings = `(rec+0xa0 bit 1) << 18`,
  and `_glrAMD_GFX9_UpdateHwBlendOptState` (`0x7f75–0x7f82`, `0x7fd0–0x7fde`) and
  `_glrAMD_GFX9_UpdateHwSxBlendOptState` (`0x81cc–0x81f3`) test exactly that. With the current Renoir
  path (Vega10 branch, flags `0x4D`) the RB+ blend-opt packets are **already skipped** — this matches
  `analysis/gl-hwinfo.md` §TL;DR point 6 and means the corruption is most plausibly the wrong
  pipe/CU/tiling model (`rec+0x78 = 4` presets, user-space AddrLib family `0x8D`) rather than those
  packets. Kernel-side `GB_ADDR_CONFIG` edits cannot flip this gate (and clearing `NUM_PIPES` bit 1
  would only corrupt user-space tiling geometry).
- The CU-count discrepancy (`rec+0x64 = 32` instead of 8) is *caused* by the user-space `rec+0x78 = 4`
  multiply, even though the kernel-feeding field `hwInfo+0x20` is already 8. A kernel patch that sets
  `hwInfo+0x20` to 2 (so that `2*4*1 = 8`) would "fix" the number but lie about CU count everywhere
  else (this field also feeds `rec+0x60` and `4*CUs-8`); do not do this.

### 4.2 If a kernel-side change is still wanted: the one clean hook

**Target symbol (15.8.1, X5000):**
`__ZN29AMDRadeonX5000_AMDAccelDevice15getHardwareInfoEP24_sAMD_GET_HW_INFO_VALUES`
(`AMDAccelDevice::getHardwareInfo(_sAMD_GET_HW_INFO_VALUES*)`, `0x4364dde`, non-virtual, T symbol).

**Technique, compatible with the existing code base:** `solveSymbol` + `KernelPatcher::RouteRequest`
(exactly like `X5000::processKext`'s other routes) or `PenguinWizardry::PatternRouteRequest` if a
pattern fallback is preferred. Wrap it, call the original, then mutate the output struct with
`getMember<UInt32>(values, off)` (the same helper used throughout `X5000.cpp` /
`X6000FB.cpp`), e.g.:

```cpp
// illustrative only, not applied
static UInt32 (*orgGetHardwareInfo)(void* self, void* values);
static UInt32 wrapGetHardwareInfo(void* self, void* values)
{
    auto ret = FunctionCast(wrapGetHardwareInfo, orgGetHardwareInfo)(self, values);
    if (ret != kIOReturnSuccess || values == nullptr) { return ret; }
    // Rewrite only after observing the real values; do NOT invent addrConfig.
    // getMember<UInt16>(values, 0x00) = NRed::singleton().getDeviceID();
    // getMember<UInt32>(values, 0x08) = ...chipRev...;       // no proven Renoir value; see table
    // getMember<UInt32>(values, 0x20) = 8;                    // already correct today
    // getMember<UInt32>(values, 0xA0) = ...real GB_ADDR_CONFIG...; // dangerous, see §4.1
    return ret;
}
```

Notes on this hook: the method is shared by **every** IOAccel client of the accelerator (GL, Metal,
and any compute client), so a rewrite affects both user-space stacks; and `getHardwareInfo` runs under
the accelerator lock while the wrapper runs after it returns, so mutating the output buffer (the
IOExternalMethod structure-output buffer, later copied to user space by IOUserClient) is safe with
respect to that lock.

**Version gating constraints:**

- The *existence* of the selector/API is not the issue — it is present in 15.8.1; `solveSymbol` failure
  must be tolerated (no-op) on OS versions where the symbol/method differs, with a
  `currentKernelVersion()` gate, exactly like the rest of the kext.
- The **field offsets are version dependent.** NootedRed's own `HWInterface.hpp` encodes three
  different `AMDHWInfo` layouts (`0xA0` for ≥ 11, `0x68` for 10.15, `0x48` for ≤ 10.14), and the GL
  bundle is version-matched to the OS. A `getHardwareInfo` hook therefore needs per-version offsets
  (and per-version struct size validation — do not assume 0x204 on older versions).
- Any rewrite must preserve the invariants `getHardwareInfo` itself checks
  (`values[0xc0..0xd8] != 0`, `values[0x00/0x18/0x20] != 0`) or user space starts failing its own
  context creation.
- Do not change `+0xa0` unless the new value matches what the kernel actually programmed into
  `GB_ADDR_CONFIG` and what the user-space AddrLib expects; otherwise tiling/swizzle/compression
  geometry diverges from hardware state.

**Expected values for Renoir / Green Sardine** (only fields where a defensible "truth" is known):

| HWInfo field | Renoir (0x1636/0x164C) | Green Sardine (0x15E7/0x1638) | Where the correct value comes from |
| --- | --- | --- | --- |
| `+0x00` deviceID | 0x1636 or 0x164C | 0x15E7 or 0x1638 | PCI config (`NRed::getDeviceID()`); already correct |
| `+0x08` chipRev/family class | currently written by the kernel as `readChipRevFromRegister()` = 1 or 2 for the Vega10Hardware class; the GL driver uses it as the branch selector (`cmpl 0x13/0x27/0x31`, so 1/2 selects the Vega10 preset) and as user AddrLib chipRevision | same | There is no proven "correct" Renoir value for this field (Linux builds chip rev from PCI revision + enumerated revision); do not substitute `NRed::getEnumRevision()` blindly |
| `+0x20` CU count | 8 | 8 (Renoir family) | `hwMaxCUs = 8` already set by `X5000::wrapSetupAndInitializeHWCapabilities`; already correct |
| `+0x88/0x90` SE/SH | 1 / 1 | 1 / 1 | already set by the same wrapper |
| `+0xa0` addrConfig | real `mmGB_ADDR_CONFIG` — value at runtime depends on what was programmed; verify before changing | same | GC reg `0x63E`; see the golden-setting discrepancy below |
| `+0x28..0x40` masks | from MCIL SH table, one SE copy is real; the other rows are currently zero/stale because NootedRed forces 1×1 | same | MCIL; not something to fabricate |

**The one questionable kernel input worth auditing.** `NootedRed/GoldenSettings.hpp:110-111`
(`gcGoldenSettingsRenoir`) programs
`GOLDEN_REGISTER(GB_ADDR_CONFIG, 0xFFFF77FF, 0x24000042)` (and the `_READ` twin) — that is the *Raven*
golden value. Linux (`gfx_v9_0.c`, `gfx_v9_0_gpu_early_init`, GC IP 9.3.0 = Renoir) uses
`read & 0xF3E777FF | 0x22010042`, which differs in `SHADER_ENGINE_TILE_SIZE` (bits 16:18 set to 1)
and in the RB/multi-GPU/row-size bits. Decoding with `GC_9_0_SH_MASK` and NootedRed's own macros in
`AMDGFX9DCNDisplay.cpp:48-53`:

- `0x24000042`: NUM_PIPES=4 pipes, NUM_SE=1, NUM_RB_PER_SE=2, SHADER_ENGINE_TILE_SIZE=0.
- Linux Renoir's RMW result: NUM_PIPES=4 pipes (bit1 set), SHADER_ENGINE_TILE_SIZE=1, different
  RB/row-size fields.

If the `sHardwareInfo+0xa0` that GL sees contains `0x24000042`-style bits, then
`arg3 & 0x70000 == 0` and the GL driver would take its "no-family" branch — which we know cannot be
what happens (AddrLib would reject family 0, and Chromium renders). Therefore either the HWInfo is
cached *before* NootedRed's golden settings are applied (firmware value, likely Vega10-class), or the
programmed value differs from the golden table on Renoir. **This must be measured on hardware before
any patch:** log `GB_ADDR_CONFIG` (`NRed::readReg32(GC_BASE_0 + 0x63E)` — MMIO access already exists
in `NRed::readReg32`) and, via a temporary `getHardwareInfo` log, the `values[0xa0]` the GLD actually
receives, before and after driver init. That single measurement decides whether the kernel side has a
real contribution or none at all.

The team already measured `arg3 = 0x00010000` on Renoir, i.e. the *class descriptor* implies
`SHADER_ENGINE_TILE_SIZE = 1`. The open question is therefore whether the kernel `AMDHWInfo+0xa0`
(arg2[0xa0], i.e. `rec+0xa4`/user-space AddrLib addrConfig) carries the same value. If it carries
NootedRed's Raven-derived `0x24000042` (tile size 0) instead, the kernel is feeding an addrConfig that
disagrees with the class descriptor that selected the branch — a genuine kernel-side inconsistency
candidate worth investigating (and one that would also explain divergent tiling decisions between
kernel and user-space AddrLib). If it carries a Renoir-like value, the kernel inputs are consistent and
the kernel side has no useful contribution; the user-space patch (A1) is the whole fix.

### 4.3 What kernel assistance would be needed if the maintainer's user-space fix wants a family

The user-space patch candidates in `analysis/gl-hwinfo.md` deliberately recommend keeping family
`0x8D` (because the bundled AddrLib only implements `FAMILY_AI`). If instead a real RV/Renoir path is
ever wanted, user space needs a *source* for the family. The kernel has it
(`AMDHardware::familyType` at object offset `0x308`, set to `0x8E` by
`X5000::initializeFamilyType`), but `AMDHWInfo` does not carry it. The clean combined design would be:
a kernel hook (same `getHardwareInfo` route) that writes the family into a mutually agreed, previously
unused HWInfo slot, plus a user-space patch that consumes it and calls user AddrLib with
`0x8E`/RV settings — which itself requires the three extra AddrLib patches noted by the sibling
analysis. That is a much larger project than patching the counts.

---

## 5. The "last bit stolen from the Navi drivers" (`X6000FB`)

### 5.1 What is actually Navi-derived

NootedRed drives the iGPU's display/framebuffer stack through Apple's **`AMDRadeonX6000Framebuffer`**
(Navi-generation FB kext). The injected personalities
(`NootedRed/Personalities/com.apple.kext.AMDRadeonX6000Framebuffer.xml:22,63,104`) bind Renoir to
`AMDRadeonX6000_AmdRadeonControllerNavi10`. On this machine `ioreg` shows
`AMDRadeonX6000_AmdRadeonControllerNavi10=1` and Navi12/14/21/22/23=0. That is the "steal": the entire
FB/display container driver is a Navi driver.

The X5000 `accel` stack (which owns 3D, and therefore blend state) is **not** Navi — it is
`AMDRadeonX5000_AMDVega10GraphicsAccelerator` (confirmed in `ioreg` `IOAccelTypes`). So the GL/3D path
that #158 corrupts does not go through `X6000FB` code at all.

What NootedRed already substitutes/reimplements in `X6000FB.cpp` (removing individual Navi assumptions):

- `AmdAsicInfoNavi10` branding vtable slot `+0x228` → Renoir/Raven/Picasso branding tables.
- `AmdRadeonControllerNavi10::createControllerServices` / `setupCursors` / `createLinks` → 4
  cursors/links/underflow trackers instead of 6, and reserved-VRAM layout reimplemented for Renoir.
- `AmdDeviceMemoryManagerNavi2::intializeReservedVram` → `X6000FB::initialiseReservedVRAM`
  (8 cursor sub-ranges + PPLIB + DMCUB regions).
- `AmdAsicInfoNavi10::getEnumeratedRevisionNumber` → NRed enum revision;
  `AmdRadeonControllerNavi1::setupBootWatermarks` → success no-op;
  `AmdRadeonControllerNavi2::getTriageHardwareData` → register-dump reimplementation.
- `populateDeviceInfo`: register read `0xD31 → 0xD2F` and family ID `0x8F (Navi) → 0x8E (Raven)`.
- DMCUB: "remove check for Navi family" + "set DMCUB ASIC constant to DCN 2.1"; VBIOS/ATOM/PSP
  helpers reimplemented; `getVendorInfo` forced to `kAGDCVendorClassIntegratedGPU`.
- CAIL `CAIL_ASIC_CAPS_TABLE` rewritten with Raven/Renoir family, DDI caps, device/revision from
  `NRed` attributes.

Still Navi-derived (not replaced by an iGPU-native implementation):

- the controller class itself (`AmdRadeonControllerNavi10`) and its power-up / display-pipe / link /
  watermark / HPD sequencing, only spot-patched where it broke;
- `AmdDeviceMemoryManagerNavi2` base behaviour (reserved VRAM partitioning, GART/FB placement) — the
  reservation *sizes/offsets* are reimplemented but the class logic is still Navi's;
- `AmdAsicInfoNavi10`/`AmdAsicInfoNavi2` class logic beyond the branding hook;
- the Navi-era `AmdFbDisplayTool`/`AmdDalHelper`/DMCUB service plumbing.

Related evidence of the same class of bug already fixed:
`CHANGELOG.md:121` "Renoir and Raven both have only 4 display pipes. Not sure where I got the previous
assumption of 6 for Renoir, maybe accidentally read from DCN 2.0 (Navi) instead of 2.1 (Renoir)", and
commit `1387173` "Fix incorrect Display Pipe count for Renoir". `X5000.cpp` also has the
`// TODO: Replace with IP Discovery?` on `wrapSetupAndInitializeHWCapabilities` and
`// TODO: Investigate why this is needed.` on the SDMA1/getHWChannel workarounds; `X6000FB.cpp:752`
has `// TODO: See amdgpu_device_need_post, ...`. There is no commit or comment that literally says
"last Navi bit"; the git log shows an ongoing cleanup series ("X6000FB: Further cleanup",
"Replace VBIOS fix once-pattern with createObjectInfo wrapper", etc.).

One more Navi-smuggling hack lives outside X6000FB, in **`HWLibs.cpp`**: `kAMDDeviceTypeNavi10` is
used as an unused firmware slot to inject Raven/Renoir VCN and DMCUB firmware
(`*orgDeviceTypeTable = {.deviceId, .deviceType = kAMDDeviceTypeNavi10}`,
`wrapPopulateFirmwareDirectory`), plus `gc_sw_init` / `psp_sw_init` "spoof" patches and the
PowerTune-services patches. That is closer to the accel/HWLibs side than X6000FB, but it is
firmware/PM initialisation, not 3D blend state.

### 5.2 Can the Navi leftover cause the #158 hangs/corruption?

Assessment: **not as a direct cause; possibly as an independent source of display/VRAM issues.**

- #158's failure is a GL command-stream/state error detected by the accel driver
  (`gpusSubmitDataBuffers` → `gpusGenerateCrashLog` → GPU reset; the command path is
  `AMDRadeonX5000GLDriver` → libGPUSupportMercury → `AMDRadeonX5000` kext). `X6000FB` does not program
  CB/SX/SPI blend or draw state.
- The X6000FB leftovers are the usual suspects for display-only symptoms (flicker, link/HPD, DMCUB
  underflow, boot watermark), and for memory-manager mistakes that could in principle overlap reserved
  VRAM with allocations used by the accelerator. No evidence of such an overlap was found, and it would
  be expected to corrupt regardless of workload rather than specifically blending-heavy workloads.
- Therefore fixing/removing the last Navi-derived behaviour is **not a plausible independent fix for
  #158**. It is worth doing for display stability separately. If the maintainer's phrase refers to the
  `AmdRadeonControllerNavi10` subclass itself, "removing" it means writing/using a real Renoir/DCN2.1
  FB controller implementation — a large project, not a small patch.

---

## 6. Priority recommendation and risks

1. **User-space patch is the only root fix for #158.** The defects are literals/branches inside
   `AMDRadeonX5000GLDriver` (`_gfx9_HwInfoInitData`/`_amdUbm_HWL_Init` family and preset constants,
   plus the CU-product bug `rec+0x64 = 32` instead of 8). See `analysis/gl-hwinfo.md` for the exact
   15.8.1 bytes/offsets and `analysis/lilu-userpatch.md` for the delivery mechanism. Kernel-only fixes
   cannot reach these.
2. **Kernel-side, do instrumentation first (cheap, decisive).** Hook
   `AMDAccelDevice::getHardwareInfo` temporarily (or add a debug-only log in
   `wrapSetupAndInitializeHWCapabilities` for `this+0x48`/`HWInfo+0xa0`) and log:
   `GB_ADDR_CONFIG` as read at init, the `values[0xa0]/[0x08]/[0x18]/[0x20]/[0x28..0x40]` the GLD
   receives, and `device+0x2e8` indirectly (which branch the GLD takes can be inferred from the
   renderer string / whether AddrLib init succeeds). This tells us definitively whether the kernel
   input set is already "Vega10-class but numerically correct", which decides whether any kernel change
   is worth pursuing.
3. **Kernel-side audit candidate:** the Renoir `GB_ADDR_CONFIG` golden value. NootedRed uses Raven's
   `0x24000042`; Linux uses an RMW `0xF3E777FF | 0x22010042` for GC 9.3.0 (Renoir). If the
   instrumentation shows the kernel exposes the Raven-programmed value to GL, changing
   `gcGoldenSettingsRenoir` to the Renoir value (and synchronising `sHardwareInfo+0xa0`/display HUBP
   programming) is a small, testable kernel-side experiment. Risks: it changes tiling geometry, so it
   must be validated on both Renoir and Green Sardine, and against NootedRed's display swizzle patches
   (`X5000.cpp` DCN1→DCN2 swizzle-mode patches) which assume a particular addr-config model.
4. **Kernel-side combined-fix enabler (optional, larger):** if user space ever wants a real RV family,
   the kernel can expose the family (`AMDHardware+0x308 = 0x8E`) through a defined fields in the
   0x204 struct via the `getHardwareInfo` hook, and the patched GLD can consume it. This requires
   also patching user-space AddrLib (`HwlConvertChipFamily`/`Create` only know AI), so it is not a
   near-term fix.
5. **Navi leftover:** treat as a separate display-side cleanup, not part of #158. If pursued, prefer
   replacing the remaining Navi subclasses/behaviours with reimplementations (as already done for
   reserved VRAM, DMCUB, VBIOS, branding) rather than more one-off patches.

Risks to call out explicitly:

- Rewriting `AMDHWInfo` fields (especially `+0xa0`, `+0x08`, `+0x18`) can desynchronise the *user-space*
  AddrLib/tiling model from the *kernel* AddrLib/display model — this class of bug can be worse than the
  one being fixed.
- `getHardwareInfo` is the user-space accelerator handshake; a broken hook can make every GL/Metal
  client fail context creation.
- Field offsets and struct size are macOS-version specific (NootedRed's own `HWInterface.hpp` proves
  this); any hook must be gated and validated per version, and must not assume 0x204.
- The user-space patch path has its own well-known risks (dyld AMFI/code-signing, per-version offsets);
  see the sibling analyses.

---

## 7. Appendix — reproduction commands and evidence index

```sh
GLD=/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver

# 1. user-space stubs -> imports
dyld_info -fixups "$GLD" > /tmp/gld.fixups
grep -E '0x0014D(178|180|188|190|198|208)' /tmp/gld.fixups
#  0x14d188 = IOAccelerator/_IOAccelDeviceGetConnect   (GLD stub 0xecf0a)
#  0x14d208 = IOKit/_IOConnectCallMethod               (GLD stub 0xecf64)

# 2. caller/argument setup (sharegroup init)
objdump -d --start-address=0x1576 --stop-address=0x1761 "$GLD"
#  or: grep -n 'glrInitializeShareGroup' /tmp/x5000gl.dis  (lines 293-405)

# 3. gfx9_HwInfoInitData projection + literals
objdump -d --start-address=0xdf40 --stop-address=0xe168 "$GLD"

# 4. kernel method dispatch + getHardwareInfo
nm -n /tmp/X5000.kext.macho | grep -E 'getHardwareInfo|getCpuGpuTimes|AMDAccelDevice'
objdump -d --start-address=0x4364d98 --stop-address=0x4364fb2 /tmp/X5000.kext.macho

# 5. kernel AMDHWInfo construction
objdump -d --start-address=0x43cba44 --stop-address=0x43cbcc0 /tmp/X5000.kext.macho   # AMDHardware::initHWInfo
objdump -d --start-address=0x43ba716 --stop-address=0x43ba91e /tmp/X5000.kext.macho   # AMDGFX9Hardware::initHWInfo
objdump -d --start-address=0x43ba3d8 --stop-address=0x43ba60c /tmp/X5000.kext.macho   # setupAndInitializeHWCapabilities
objdump -d --start-address=0x43c9226 --stop-address=0x43c9600 /tmp/X5000.kext.macho   # AMDHardware::init (PCI cfg -> HWInfo)
# getHWInfo getter (vtable slot +0x1C0 target): 0x43c6e8c  -> lea 0xd0(%rdi),%rax ; ret

# 6. gfx9 register definitions used for decoding
curl -s https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpu/drm/amd/include/asic_reg/gc/gc_9_0_sh_mask.h | \
  grep -n 'GB_ADDR_CONFIG__'
curl -s https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpu/drm/amd/include/asic_reg/gc/gc_9_0_offset.h | \
  grep -n 'GB_ADDR_CONFIG\|GB_GPU_ID'
#  mmGB_ADDR_CONFIG = 0x063E ; NUM_PIPES mask 0x7 shift 0 ; SHADER_ENGINE_TILE_SIZE mask 0x70000 shift 0x10
#  NUM_SHADER_ENGINES mask 0x180000 shift 0x13 ; NUM_RB_PER_SE mask 0xC000000 shift 0x1A

# 7. Linux reference values for APUs
curl -s https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpu/drm/amd/amdgpu/gfx_v9_0.c | \
  grep -n 'GB_ADDR_CONFIG_GOLDEN\|gb_addr_config &= ~'
#  RAVEN=0x24000042 RAVEN2=0x26013041 VEGA10=0x2a114042 VEGA12=0x24104041
#  Renoir (GC 9.3.0): RREG32(mmGB_ADDR_CONFIG) & 0xF3E777FF | 0x22010042

# 8. NootedRed golden settings (kernel side)
grep -n 'GB_ADDR_CONFIG' NootedRed/GoldenSettings.hpp
```

Evidence map for the claims above:

| Claim | Evidence |
| --- | --- |
| GLD arg2 is the kernel `AMDHWInfo` memcpy | GLD `0x15df–0x1640`; X5000 `0x4364dde–0x4364e66`; selector 0x100 method-table slot `0x457e750` (fn `0x4364dde`, size 0x204) |
| `AMDHWInfo` at `AMDHardware+0xd0`, size 0x204 | `0x43cba7b` memset; `0x43c6e8c` getter; `0x43ba716+` field stores |
| `GB_ADDR_CONFIG` source and path into HWInfo | `0x43ba41f–0x43ba461` GC MMIO reads (`*0x118`, reg `0x63E + this+0x206bc` etc.); `0x43ba4e6–0x43ba4ec` stores the `0x63E` value into `this+0x48` (`-0x104(%rbp)` held `r14d`); `0x43cbad4–0x43cbae5` copies `this+0x48` → `this+0x170` = `HWInfo+0xa0` |
| GL hardcodes family 0x8D / presets | `0xdf40–0xe163` (`movl $0x8d,(%rdi)` @ `0xe07b/0xe0c6/0xe103`; `movl $4,0x78(%rdi)`; preset writes) |
| GL AddrLib accepts only 0x8D/0x8F and only implements AI | GLD `0x681a0` (`Addr::Lib::Create`), `0x7d940` (`Gfx9Lib::HwlConvertChipFamily`) |
| BLEND-OPT/settings gate source | `0x60098` (`_glrAMD_GFX9_InitDriverSettings`) reads `rec+0xa0` (branch flags, not kernel `GB_ADDR_CONFIG`); `(flags&2)<<18` → settings bit19; `0x7f75–0x7f82`, `0x7fd0–0x7fde`, `0x81cc–0x81f3` test `settings byte[2]&8` / `rec+0xa0&2`. Kernel addrConfig goes to `rec+0xa4`. |
| `device+0x2e8` never written by the GLD | exhaustive store scan of GLD `__text`; reads at `0x1630`, `0x1d067`, `0x48eef` (before its own IOKit calls) |
| X6000FB Navi binding | `Personalities/...X6000Framebuffer.xml:22,63,104`; `ioreg` class counts; `X6000FB.cpp` patch table |

Caveats/limits of this analysis:

- No hardware was instrumented; all runtime statements about which branch Renoir takes are inferences
  from the code plus the known-working-(corrupted) state of GL on this machine.
- libGPUSupportMercury (dyld shared cache) was not disassembled: the exact kernel field that fills
  `device+0x2e8` is unproven (only its consumer-side packing is proven).
- Only the macOS 15.8.1 kext/GLD builds were analysed. Symbol names, field offsets, struct size and
  selector numbers must be re-verified for each supported macOS version before any patch is attempted.
