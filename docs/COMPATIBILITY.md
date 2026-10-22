# NootedRed compatibility matrix

Status date: 2026-10-22. This table describes what the current tree actually enables, not what the
hardware could theoretically do. A feature is only `validated` when it has passed a real boot and the
corresponding feature test on that exact build **and** APU.

The historical `validated` entries below are upstream-reported results, not hardware validation of
this combined 0.9.4 build. Local 0.9.1 Renoir `0x1636` / Sonoma `23J631` tests found a compute hang even
with GLFix and VDA disabled; short decode probes passed on 0.9.0, while encoding produced incorrect
pixels. This integration has host checks only; a macOS build and hardware validation are pending.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| **validated** | Real hardware boot + feature test passed for this exact build/APU. |
| **experimental** | Implementation/data exists and is build- or offline-validated, but no hardware test has passed. |
| **supported** | The kext-level path exists for this build, but this is not a claim about the feature-specific data below. |
| **unsupported** | No data or no code path for this build; the feature is a no-op or refuses to run. |
| **no-op** | The code is present, but the exact build/driver pages do not match, so nothing is written. |

## macOS build matrix

| macOS build | Darwin | Kernel / graphics | GLFIX GL | GLFIX Metal | VDA/VCN kernel bridge | VDA user-space (VA + AppleGVA) | HEVC encode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **15.8.1 (24H32)** | 24.6.0 | supported | **validated** (`0x1638`) | **validated** (`0x1638`) | **validated** (`24H32` data) | **validated** (`VDAVAData`, `VDAGVAData`) | **validated** (`0x1638`) |
| **14.8.9 (23J631)** | 23.6.0 | supported | experimental (exact pages + semantic/signature fallback, offline) | experimental (exact pages + semantic/signature fallback, offline) | experimental (imported `23J631` data, byte-gated) | experimental (imported `VDAVADataSonoma`, `VDAGVADataSonoma`) | experimental (imported data) |
| **26.7.1 (25G241)** | 25.6.0 | supported | experimental (`TahoePatchData`, offline) | experimental (`TahoePatchData` gate/allow, offline) | experimental (`25G241` data, hardware pending) | experimental (`VDAVADataTahoe`, `VDAGVADataTahoe`, hardware pending) | experimental (26.7.1 data, hardware pending) |
| other 15.x (`24G*`/`24H*`) | 24.x | supported | experimental (semantic/exact) | experimental (semantic/exact) | experimental (`24G`/`24H` family fallback, byte-gated) | experimental/no-op (reference pages/site contexts) | experimental |
| other 14.x (`23H*`/`23G*`/`23J*`) | 23.x | supported | experimental (semantic/exact) | experimental (semantic/exact) | experimental (`23J`/`23H`/`23G` family fallback, byte-gated) | experimental (`VDAVADataSonoma`, exact pages) | experimental |
| other 26.x | 25.x | supported | experimental/no-op (semantic/exact) | experimental/no-op (semantic/exact) | experimental (`25G` family fallback, byte-gated) | experimental/no-op (reference pages/site contexts) | experimental |
| Catalina 10.15 – Ventura 13 | 19–22 | supported | unsupported/no-op | unsupported/no-op | **unsupported** | **unsupported** | **unsupported** |

Notes:

- "Kernel / graphics" means the NootedRed kext itself loads and the existing X5000/HWLibs/display
  patches run. It does not imply GLFIX or VDA.
- GLFIX is opt-in with `-NRedGLFix` (`-NRedGLFixOff` forces it off). The semantic fallback is a no-op
  when its instruction contexts do not match.
- VDA/VCN is opt-in (`-NRedVDA`, `-NRedAVC` for AVC-only, or `-NRedAVCEncode` to retain HEVC encoding). Without matching data the boot argument is
  ignored and the system stays on software decode.
- macOS 26.7.1 GL/MTL images are from the `25G241` external datasets; this project has not booted
  them on hardware itself.
- VCN family-prefix adapters reuse the nearest validated table (`23J631`, `24H32`, `25G241`) for nearby
  patch releases.  Every guard/getter and original call-site byte is still checked; a changed kernel is
  a no-op.  These adapters are not a substitute for a build-specific VDA page table.
- Other 15.x/14.x builds can still use the semantic GL path (14.x also keeps semantic scanning when its
  exact Sonoma pages are selected).

- This fork preserves Weachy's signature resolver as the final rendering fallback, enabled with GLFIX.
  A version/APU match keeps semantic GL/Metal scanning available; an applied exact rendering page stops
  it unless `-NRedGLFixSemanticMTL` explicitly forces it. `-NRedGLFixSemanticOff` wins.
- Native site fallback requires every original patch site and 16 bytes of surrounding code on each
  side to match. VDA still requires a ready bridge. Changed contexts remain unpatched.
- Metal SubmitGuard is enabled by default on Darwin 23/24/25, independently of GLFIX/VDA. It verifies
  the known method prologue at the OS-specific address; this does not guarantee all builds match.
  `-NRedNoSubmitGuard` disables it. Its stability benefit needs a new hardware test.
- Non-AMD discrete GPUs no longer block VDA. External AMD GPUs still block it unless
  `-NRedForceVDA` overrides that check. `-NRedVCNNoGfxOff` is an optional diagnostic hold.

## APU matrix

| APU / device ID | VCN generation | GLFIX (15.8.1) | VDA/VCN (15.8.1) | VDA/VCN (26.7.1) |
| --- | --- | --- | --- | --- |
| Renoir / Green Sardine `0x1638` | VCN 2.2 | **validated** | **validated** | experimental (data present, hardware pending) |
| Renoir `0x1636` | VCN 2.2 | experimental | experimental (same 15.8.1 data; hardware not validated) | experimental (data present, hardware pending) |
| Cezanne `0x164C` | VCN 2.2 | experimental | experimental | experimental (data present, hardware pending) |
| Barcelo `0x15E7` | VCN 2.2 | experimental | experimental | experimental (data present, hardware pending) |
| Raven `0x15DD` | VCN 1.x | experimental | **unsupported** (no VCN1 path) | **unsupported** |
| Raven2 / Picasso `0x15D8` | VCN 1.x | experimental | **unsupported** (no VCN1 path) | **unsupported** |

The GLFIX page data is shared across gfx9 APUs for the listed builds, but only `0x1638` on 15.8.1 has a
recorded hardware validation.

## Feature/flag matrix

| Feature | Flag | 15.8.1 | 14.8.9 | 26.7.1 |
| --- | --- | --- | --- | --- |
| GL dual-source fix | `-NRedGLFix` | validated | experimental (exact Sonoma pages) | experimental (exact 25G241 pages) |
| Metal dual-quad fix | included with GLFIX | validated | experimental (exact Sonoma pages) | experimental (gate/allow, hardware pending) |
| VCN2 hardware decode | `-NRedVDA` | validated | experimental (imported) | experimental (25G241, hardware pending) |
| AVC-only mode | `-NRedAVC` | validated | experimental (imported) | experimental (25G241, hardware pending) |
| VCN kernel bridge | `-NRedVDA`/`-NRedAVC` | validated | experimental (byte-gated) | experimental (25G241) |
| VDA user-space VA/GVA | with VDA flags | validated | experimental (imported) | experimental (`VDAVADataTahoe`/GVA) |
| HEVC encode | `-NRedVDA` | validated | experimental (imported) | experimental (25G241, hardware pending) |

| H.264 decode + HEVC encode | `-NRedAVCEncode` | experimental | experimental | experimental |
| Metal SubmitGuard | default; `-NRedNoSubmitGuard` disables | experimental | experimental | experimental |

`-NRedAVC` takes precedence if combined with other video modes and removes both HEVC capabilities.
`-NRedAVCEncode` disables HEVC hardware decoding while preserving HEVC hardware encoding. Hardware
encode capability being exposed is not proof of correct output; local earlier tests found bad pixels.

## What "macOS 26 support" means here

- The kext range already includes macOS 26 (Darwin 25) and the GLFIX/Metal 26.7.1 data path exists.
- **VDA/VCN on macOS 26** now has `25G241` kernel call-site data and `VDAVADataTahoe`/`VDAGVADataTahoe`,
  but is still experimental until a real 26.7.1 boot/decode/encode test passes. Other builds only attempt the declared kernel-family adapters and contextual page fallbacks;
  matching a family does not establish video compatibility.
- `25G241` kernel data is now in `VCNData/25G241.hpp`; the user-space VDA tables are
  `VDAVADataTahoe.hpp` / `VDAGVADataTahoe.hpp`. The remaining work is a real 26.7.1 boot and
  decode/encode test on the target APU; only then can this row become `validated`.
- For another 26.x build, collect `SystemKernelExtensions.kc`, `AMDRadeonVADriver2`, AppleGVA pages and
  platform metadata on that build, generate the same data set, and hardware-validate it; 15.8.1 or
  26.7.1 data must not be labeled validated for a different build.

## Evidence

- [Architecture](ARCHITECTURE.md) — kernel plane vs root-patch plane and versioning policy.
- [Platform data index](Platform-Data-Index.md) — collected datasets, including the 26.7.1 GL/MTL data.
- [Archived 26.7.1 support note](archive/Tahoe-26.7.1-Support.md) — GL/Metal data derivation and the
  open runtime-validation task.
- `NootedRed/TahoePatchData.hpp` — 26.7.1 exact GL/MTL pages.
- `NootedRed/VCNData/24H32.hpp` / `23J631.hpp` — the two VCN builds that exist today.
