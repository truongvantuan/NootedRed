# Combined NootedRed 0.9.4 (DP recovery candidate)

This fork combines the `master` branches of
[Weachy](https://github.com/weachy/NootedRed) and
[xiaot-evo](https://github.com/xiaot-evo/NootedRed), preserving this repository's local compiler and CI fixes.
The integration records both upstream histories as merge parents so future updates can use normal Git merges.

## Sources integrated on 2026-10-20

| Source | Revision | Contribution |
| --- | --- | --- |
| Weachy | `ea71183b0c3b21acf222a22100d6aa3ee3b682c7` | Sonoma/Sequoia VDA data, AVC-only mode, minor-series VDA gates, Sonoma resolver, OS-specific GL/Metal tables |
| xiaot-evo | `348948e1636b1a19fdf35e77700f3217328d24d2` | Semantic GL/Metal fallback, Tahoe gate/allow fix, reduced scanning, exact-build VCN variants, timestamped archives and documentation |
| Local baseline | `ded3289a81cff99d3e1123b621fd02561811708c` | Compiler compatibility and release CI |

Only these two forks' `master` branches are integrated. Research branches and other forks are excluded.

0.9.4 extends the opt-in local DisplayPort receiver pre-wake candidate with a guarded transmitter
BIOS-loop deadline, currently limited to the inspected Renoir/23J631 framebuffer. The 0.9.3
receiver-only power-button trials failed; the 0.9.4 hardware result is pending. See
[DisplayPort recovery](DisplayPort-Recovery.md) for the evidence, constraints and diagnostics.

xiaot-evo force-rewrote its earlier history; the old `11dac5c` integration and the rewritten upstream
tip are both retained as ancestors. The update compares the old/new source snapshots to preserve local
compiler fixes, regression tools and Weachy's resolver behavior. The new architecture/root-patch files
are upstream design proposals; this version does not ship or install a companion root patcher.

## Rendering patch priority

1. Exact driver-page images are checked first, including OS-family tables when the Darwin minor has no
   dedicated entry. VA/AppleGVA pages additionally require a ready VCN bridge.
2. A version/APU-matched native set disables semantic scanning by default, reducing repeated page scans.
   `-NRedGLFixSemanticMTL` explicitly restores semantic scanning for QA; `-NRedGLFixSemanticOff` wins.
   Without a matched set, semantic GL matching follows on unmatched pages and semantic Metal scanning
   is automatic. OS-family exact pages remain the first path.
3. The selected Sonoma/Sequoia signature resolver is the final fallback. It is enabled with the GL fix
   by default, following Weachy's policy.

Known Tahoe pages now use xiaot-evo's gate/allow Metal fix (including the second allow-pattern occurrence),
replacing 0.9.1's experimental direct-field strategy. Experimental direct-field data remains available to
the semantic QA/fallback path, but it is not the default exact-page Tahoe patch. Disabling the profile's
graphics policy disables both fallback mechanisms. GLFix remains off by default.

## Boot arguments

Keep your existing unrelated boot arguments and append the desired feature flags.

| Argument | Effect |
| --- | --- |
| `-NRedGLFix` | Opt into exact rendering pages and automatic signature fallback; semantic scanning depends on patch-set selection |
| `-NRedGLFixOff` | Disable the rendering fix; overrides `-NRedGLFix` |
| `-NRedGLFixSemanticMTL` | Explicitly enable semantic GL/Metal scanning even when a version-matched patch set exists |
| `-NRedGLFixSemanticOff` | Disable semantic GL and Metal matching; exact pages and resolver remain available |
| `-NRedGLFixResolveOff` / `-NRedGLFixNoResolve` | Disable the signature resolver, including resolver-only QA mode |
| `-NRedGLFixResolve` | Legacy flag; redundant because the resolver is enabled with `-NRedGLFix` |
| `-NRedGLFixResolveOnly` | GL QA mode: skip exact GL pages and semantic matching; VA/AppleGVA exact patches remain available |
| `-NRedVDA` | Request experimental H.264 and HEVC video acceleration |
| `-NRedAVC` | Request the video bridge but remove HEVC decode/encode capability properties; overrides `-NRedVDA` |
| `-NRedDPFix` | Experimental direct-DP receiver pre-wake and guarded BIOS-loop deadline for the exact inspected Renoir/23J631 framebuffer; hardware verification pending |

For your existing full video configuration:

```text
-NRedGLFix -NRedVDA
```

For H.264-only mode, replace `-NRedVDA` with `-NRedAVC`. The mode does not disable H.264 encoding or
repair encoder output. For exact rendering-page matching only, use:

```text
-NRedGLFix -NRedGLFixSemanticOff -NRedGLFixResolveOff
```

The standard NootedRed switches (`-NRedOff`, `-NRedDebug`, `-NRedBeta`, `-NRedNoAccel`,
`-NRedDPDelay`, `AMDBacklight=0/1`, and debug extensions) remain supported.

## Video compatibility

The bridge now requires exactly Sonoma 14.8.9 `23J631` / Darwin 23.6, or Sequoia 15.8.1 `24H32` /
Darwin 24.6, and a supported VCN2 APU (`1636`, `1638`, `164C`, `15E7`) without an external GPU. This
replaces 0.9.1's broad `23J`/`24H` prefix eligibility; unknown, empty, or suffixed build identifiers do
not select an X6000 variant. The early X5000 path can select guards by Darwin version before the build
string is populated, but X6000 writes require the exact build. ABI guards, call-site bytes and exact
VA/AppleGVA page images must still match. Tahoe VDA is not enabled.

Each supported build has a separate `VCNData/<build>.hpp`. `NRedVCNDataVariant` reports 1 for Sonoma or
2 for Sequoia. `NRedVCNDataIdentityAvailable` distinguishes imported data without local identity from
identity-bearing generated data; it is provenance metadata, not a fresh runtime UUID/SHA verification.

## Build and verify

```sh
xmake f -m release -a x86_64 -y
sh tools/build-branch.sh -y
python3 tools/test_patch_data.py
python3 tools/test_patchset_selection.py
python3 tools/test_gl_semantic_data.py
python3 tools/test_patch_dispatch.py
python3 tools/test_vcn_multibuild.py
python3 tools/test_dp_recovery.py
python3 tools/test_atom_loop_guard.py
python3 tools/test_atom_native_vm.py
```

Artifacts are under `build/branches/<sanitized-branch>/macosx/x86_64/release/`.
The kext and ZIP report version 0.9.4. New ZIPs include a local timestamp; older canonical archives are
preserved. See [Build-Artifacts.md](Build-Artifacts.md).

Host checks validate reference bytes, selection ranges, native-page dispatch with kernel calls stubbed,
and the compiled production VCN selector against valid/invalid build identifiers. They do not establish
boot, rendering, playback, encoding or sleep/wake stability. Version 0.9.2 needs a separate hardware boot
before it can be called validated.

Local Renoir `0x1636` / Sonoma `23J631` 0.9.1 tests loaded the same DEBUG executable with (a) GLFix+VDA,
(b) GLFix alone, and (c) both optional features disabled. All three experienced a compute queue hang and
channel reset, at approximately 89.8, 89.4, and 32.3 seconds after boot. These optional features are not
required to trigger that failure; this update makes no claim to repair it. Earlier short 0.9.0 hardware
decode probes passed, while encoding produced incorrect pixels. Hardware validation is per build and
feature, not implied by successful initialization markers.

After installing and booting the new kext, run `bash tools/vda_selftest.sh` and, when ready to exercise
the GPU, `bash tools/vda_hwtest.sh`. Both accept VDA or AVC-only mode; AVC-only tests skip HEVC.

## Future upstream updates

```sh
git fetch weachy master
git fetch xiaot-evo master
git merge weachy/master
git merge xiaot-evo/master
```

Resolve overlaps against the combined behavior above, preserve local build fixes, run the host checks,
and rebuild before deployment. The `origin` remote continues to point to your own repository.
If an upstream branch is force-rewritten again, compare its previous and new tips before resolving a
merge; do not replace the combined source wholesale just because the apparent new-commit count is large.
