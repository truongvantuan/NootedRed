# NootedRed compatibility matrix

Status date: 2026-10-20. This table describes what the current tree actually enables, not what the
hardware could theoretically do. A feature is only `validated` when it has passed a real boot and the
corresponding feature test on that exact build **and** APU.

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
| **14.8.9 (23J631)** | 23.6.0 | supported | experimental (semantic, offline) | experimental (semantic, offline) | experimental (imported `23J631` data, byte-gated) | experimental (imported `VDAVADataSonoma`, `VDAGVADataSonoma`) | experimental (imported data) |
| **26.7.1 (25G241)** | 25.6.0 | supported | experimental (`TahoePatchData`, offline) | experimental (`TahoePatchData` direct-field, offline) | **unsupported** (no `25G241` kernel data) | **unsupported** (no macOS 26 VA/AppleGVA data) | **unsupported** |
| other 15.x (`24H*`) | 24.x | supported | experimental/no-op (semantic) | experimental/no-op (semantic) | **unsupported** (exact `24H32` only) | **unsupported** | **unsupported** |
| other 14.x (`23J*`) | 23.x | supported | experimental/no-op (semantic) | experimental/no-op (semantic) | **unsupported** (exact `23J631` only) | **unsupported** | **unsupported** |
| other 26.x | 25.x | supported | **no-op/unsupported** (exact `25G241` pages only) | **no-op/unsupported** (exact `25G241` pages only) | **unsupported** | **unsupported** | **unsupported** |
| Catalina 10.15 – Ventura 13 | 19–22 | supported | unsupported/no-op | unsupported/no-op | **unsupported** | **unsupported** | **unsupported** |

Notes:

- "Kernel / graphics" means the NootedRed kext itself loads and the existing X5000/HWLibs/display
  patches run. It does not imply GLFIX or VDA.
- GLFIX is enabled by default (`-NRedGLFix` confirms it; `-NRedGLFixOff` disables it). The semantic
  fallback is a no-op when its instruction contexts do not match.
- VDA/VCN is opt-in (`-NRedVDA`, or `-NRedAVC` for AVC-only). Without matching data the boot argument is
  ignored and the system stays on software decode.
- macOS 26.7.1 GL/MTL images are from the `25G241` external datasets; this project has not booted
  them on hardware itself.
- Other 15.x/14.x builds can still use the semantic GL path, but the VCN/VDA tables are exact-build and
  therefore intentionally unavailable.

## APU matrix

| APU / device ID | VCN generation | GLFIX (15.8.1) | VDA/VCN (15.8.1) | VDA/VCN (26.7.1) |
| --- | --- | --- | --- | --- |
| Renoir / Green Sardine `0x1638` | VCN 2.2 | **validated** | **validated** | **unsupported** (data pending) |
| Renoir `0x1636` | VCN 2.2 | experimental | experimental (same 15.8.1 data; hardware not validated) | **unsupported** |
| Cezanne `0x164C` | VCN 2.2 | experimental | experimental | **unsupported** |
| Barcelo `0x15E7` | VCN 2.2 | experimental | experimental | **unsupported** |
| Raven `0x15DD` | VCN 1.x | experimental | **unsupported** (no VCN1 path) | **unsupported** |
| Raven2 / Picasso `0x15D8` | VCN 1.x | experimental | **unsupported** (no VCN1 path) | **unsupported** |

The GLFIX page data is shared across gfx9 APUs for the listed builds, but only `0x1638` on 15.8.1 has a
recorded hardware validation.

## Feature/flag matrix

| Feature | Flag | 15.8.1 | 14.8.9 | 26.7.1 |
| --- | --- | --- | --- | --- |
| GL dual-source fix | `-NRedGLFix` (default on) | validated | experimental (semantic) | experimental (exact 25G241 pages) |
| Metal dual-quad fix | included with GLFIX | validated | experimental (semantic) | experimental (direct-field, runtime pending) |
| VCN2 hardware decode | `-NRedVDA` | validated | experimental (imported) | unsupported |
| AVC-only mode | `-NRedAVC` | validated | experimental (imported) | unsupported |
| VCN kernel bridge | `-NRedVDA`/`-NRedAVC` | validated | experimental (byte-gated) | unsupported |
| VDA user-space VA/GVA | with VDA flags | validated | experimental (imported) | unsupported |
| HEVC encode | `-NRedVDA` | validated | experimental (imported) | unsupported |

## What "macOS 26 support" means here

- The kext range already includes macOS 26 (Darwin 25) and the GLFIX/Metal 26.7.1 data path exists.
- **VDA/VCN on macOS 26 is not implemented** in this tree: there is no `25G241` kernel-collection
  call-site data and no macOS 26 `AMDRadeonVADriver2`/AppleGVA page data. Fabricating a variant from
  the 15.8.1 tables would violate the exact-build/byte-verification contract.
- To add it, collect on the target 26.7.1 machine:
  - `SystemKernelExtensions.kc` (X5000/X6000 symbols and text);
  - `AMDRadeonVADriver2` and AppleGVA shared-cache images/pages;
  - the platform metadata used by `tools/collect_compat_data.py --include-kc`.
  Then generate a `VCNData/25G241.hpp` variant and the VA/GVA tables, add selection entries, and run
  the hardware validation on the target APU before changing the matrix.

## Evidence

- [Architecture](ARCHITECTURE.md) — kernel plane vs root-patch plane and versioning policy.
- [Platform data index](Platform-Data-Index.md) — collected datasets, including the 26.7.1 GL/MTL data.
- [Archived 26.7.1 support note](archive/Tahoe-26.7.1-Support.md) — GL/Metal data derivation and the
  open runtime-validation task.
- `NootedRed/TahoePatchData.hpp` — 26.7.1 exact GL/MTL pages.
- `NootedRed/VCNData/24H32.hpp` / `23J631.hpp` — the two VCN builds that exist today.
