# Combined NootedRed 0.9.1

This fork combines the `master` branches of
[Weachy](https://github.com/weachy/NootedRed) and
[xiaot-evo](https://github.com/xiaot-evo/NootedRed), preserving this repository's local compiler and CI fixes.
The integration records both upstream histories as merge parents so future updates can use normal Git merges.

## Sources integrated on 2026-10-20

| Source | Revision | Contribution |
| --- | --- | --- |
| Weachy | `ea71183b0c3b21acf222a22100d6aa3ee3b682c7` | Sonoma/Sequoia VDA data, AVC-only mode, minor-series VDA gates, Sonoma resolver, OS-specific GL/Metal tables |
| xiaot-evo | `11dac5c1224d10a1064e07f86e5dceb25b531b3a` | Semantic GL/Metal fallback, validation tools, patch architecture and research documentation |
| Local baseline | `ded3289a81cff99d3e1123b621fd02561811708c` | Compiler compatibility and release CI |

Only these two forks' `master` branches are integrated. Research branches and other forks are excluded.

## Rendering patch priority

1. Exact driver-page images are checked first, including OS-family tables when the Darwin minor has no
   dedicated entry. VA/AppleGVA pages additionally require a ready VCN bridge.
2. Semantic GL matching follows on unmatched pages. Semantic Metal scanning is automatic when no
   version-matched patch set exists, or can be explicitly requested.
3. The selected Sonoma/Sequoia signature resolver is the final fallback. It is enabled with the GL fix
   by default, following Weachy's policy.

Known Tahoe pages use xiaot-evo's direct-field Metal fix. Weachy's gate/allow variant remains in the
semantic variant table for pages without the direct form; the two strategies are not applied together
to a known page. Disabling the profile's graphics policy disables both fallback mechanisms.

## Boot arguments

Keep your existing unrelated boot arguments and append the desired feature flags.

| Argument | Effect |
| --- | --- |
| `-NRedGLFix` | Opt into the rendering fix: exact pages, semantic GL fallback and signature fallback |
| `-NRedGLFixOff` | Disable the rendering fix; overrides `-NRedGLFix` |
| `-NRedGLFixSemanticMTL` | Enable semantic Metal scanning even when a version-matched patch set exists |
| `-NRedGLFixSemanticOff` | Disable semantic GL and Metal matching; exact pages and resolver remain available |
| `-NRedGLFixResolveOff` / `-NRedGLFixNoResolve` | Disable the signature resolver, including resolver-only QA mode |
| `-NRedGLFixResolve` | Legacy flag; redundant because the resolver is enabled with `-NRedGLFix` |
| `-NRedGLFixResolveOnly` | GL QA mode: skip exact GL pages and semantic matching; VA/AppleGVA exact patches remain available |
| `-NRedVDA` | Request experimental H.264 and HEVC video acceleration |
| `-NRedAVC` | Request the video bridge but remove HEVC decode/encode capability properties; overrides `-NRedVDA` |

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

The bridge accepts Darwin 23.6 with build prefix `23J`, or Darwin 24.6 with prefix `24H`, and a supported
VCN2 APU (`1636`, `1638`, `164C`, `15E7`) without an external GPU. This broadens eligibility within those
series; it does not guarantee acceleration on every update. The generated ABI guards, call-site bytes
and exact VA/AppleGVA page images must still match. The reference data comes from Sonoma 14.8.9
(`23J631`) and Sequoia 15.8.1 (`24H32`). Tahoe VDA is not enabled.

## Build and verify

```sh
xmake f -m release -a x86_64 -y
sh tools/build-branch.sh -y
python3 tools/test_patch_data.py
python3 tools/test_patchset_selection.py
python3 tools/test_gl_semantic_data.py
python3 tools/test_patch_dispatch.py
```

Artifacts are under `build/branches/<sanitized-branch>/macosx/x86_64/release/`.
The kext and ZIP report version 0.9.1. See [Build-Artifacts.md](Build-Artifacts.md).

Host checks validate reference bytes, selection ranges and native-page dispatch with kernel calls stubbed.
They do not establish boot, rendering, playback, encoding or sleep/wake stability. This combined revision
needs a separate hardware boot before it can be called validated. Earlier Renoir/Sonoma tests established
decoding but found incorrect encoder output and a boot-time compute timeout; this merge makes no claim to
repair those issues.

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
