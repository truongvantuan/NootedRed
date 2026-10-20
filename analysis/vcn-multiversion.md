# VCN decode multi-version support

Status: infrastructure implemented and build-verified; macOS 15.8.1 is hardware-validated on Renoir
`0x1638`, macOS 14.8.9 is imported from the multi-OS fork and **not hardware-tested here**.

## Scope

VCN decode used to be pinned to one kernel collection + one dyld-cache pair (macOS 15.8.1 / 24H32) and the
bridge refused every other build.  The multi-version layer selects a complete per-build data set:

| Build | Darwin | Kernel call sites | AMDRadeonVADriver2 | AppleGVA | Source |
| --- | --- | --- | --- | --- | --- |
| macOS 15.8.1 (24H32) | 24.6.0 | `CallPatches` (20) | `VDAVAData` (9 records / 12 sites / 8 pages) | `VDAGVAData` (1 record) | generated in this tree |
| macOS 14.8.9 (23J631) | 23.6.0 | `CallPatches_Sonoma` (20) | `VDAVADataSonoma` (9 / 12 / 8) | `VDAGVADataSonoma` (1) | imported from [`weachy/NootedRed`](https://github.com/weachy/NootedRed) |
| macOS 26.x (Tahoe) | 25.x | — | — | — | not generated yet; bridge rejects |

The 14.8.9 headers carry the exact source identity in their comments: AMDRadeonVADriver2 5.5.20, AppleGVA
113.54.1, dyld cache `4C1441FD8A543DC2863D49110B946A25`, and the corresponding `__text`/page hashes.  The
kernel-side Sonoma call-site table comes from the same fork's multi-OS VDA work
(`569b453` / `0c65bd6`); its `original` bytes are verified on the live X6000 text before any write.

## Selection flow

```
NRed::init()
  Darwin major 23 → register VDAVADataSonoma / VDAGVADataSonoma
  Darwin major 24 → register VDAVAData / VDAGVAData
  other           → register nothing

VCNBridge::init()
  requested = -NRedVDA || -NRedAVC
  isSupportedOS(): (24.6) || (23.6)

VCNBridge::isSupportedBuild()       (at accelerator start, when osversion is populated)
  24.x → build prefix "24H"
  23.x → build prefix "23J"
  empty→ ABI guards remain the protection

VCNBridge::processKext(X5000)
  verifies vtable/getter guards (shared 15.8.1 guard arrays)
  publishes NRedVCNDataVariant (1 = Sonoma, 2 = Sequoia)

VCNBridge::processKext(X6000)
  getCallPatches(count) → CallPatches_Sonoma for Darwin 23, CallPatches for Darwin 24
  verify every original byte; all-or-nothing write
```

The user-space `UserPatches` backend uses the normal `-NRedVDA`/`-NRedAVC` gate, the VCN 2.x profile gate
and `VCNBridge::loadReady()`.  It receives the per-build table registered above; a page that does not match
the running cache/build is a no-op.

## `-NRedAVC`

`-NRedAVC` opts into the same VCN bridge and user-space tables but removes the HEVC decode/encode
capabilities from the injected X5000 personality:

- AVC/H.264 still uses the hardware VCN engine;
- HEVC is left to software (avoids the unstable HEVC path seen on some Sonoma-era builds);
- `NRedVDAAVCOnly=1` and the `VDA` log line show the selected mode.

`-NRedVDA` keeps full AVC + HEVC hardware decode.

## Known risk

The kernel vtable/getter guard arrays are still the 15.8.1 data for both versions.  If Apple changed the
X5000/X6000 vtable layout on 14.8.9, the guard comparison fails and the bridge disables itself (fail-closed,
software decode).  A real 14.8.9 Sonoma boot with `-NRedVDA` (or `-NRedAVC`) is required to confirm the
guards and the 20 call sites before this can be marked hardware-validated.  Regenerating the Sonoma kernel
data with `tools/gen_vcn_kernel_data.py` from a Sonoma machine would remove that uncertainty.

## Adding another build

1. Run [`tools/collect_compat_data.py`](../tools/README-collect-compat-data.md) on the target build with
   `--include-kc`; keep the kernel collection and dyld cache.
2. Generate the three headers for that build:
   - `tools/gen_vcn_kernel_data.py`
   - `tools/gen_vda_va_data.py`
   - `tools/gen_vda_gva_data.py`
3. Add the generated table set under a new namespace/name, add the build to `getCallPatches()` and
   `NRed::init()` selection, and extend the build prefix checks in `VCNBridge`.
4. Extend `tools/test_vcn_multibuild.py` with the new records/sites/pages and run:
   ```sh
   xmake -y
   python3 tools/test_vcn_multibuild.py
   ```
5. Only mark the build supported after a real boot + decode test on the matching APU.
