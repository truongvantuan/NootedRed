# Combined NootedRed 1.0.0

This fork combines the `master` branches of [Weachy](https://github.com/weachy/NootedRed) and
[xiaot-evo](https://github.com/xiaot-evo/NootedRed), preserving local compiler fixes, CI and regression tools.

## Sources integrated on 2026-10-22

| Source | Revision | Changes integrated |
| --- | --- | --- |
| Weachy | `3b37dfc6282016608962b2746d7809765ad121f4` | Previous integration plus corrected SubmitGuard syscall ABI and shared-cache base lookup, FairPlay VDA exclusion, dynamic Metal LegacyBlend, compatibility collector improvements and version 1.0.0 |
| xiaot-evo | `0efa6f4f36117fb603be968c1341006bf4da8c37` | Tahoe VCN variant, family-prefix variants, corrected semantic scan stopping point, Firefox/Zen launcher |
| Previous combined baseline | `2e88d17` | Local compiler/CI fixes, OS-specific rendering tables, semantic and signature fallback, per-build VCN data |

Both source tips are recorded as merge ancestors. xiaot-evo rewrote its history again; its previous
integrated `348948e` tree is identical to the rewritten `a4da11c` tree. The integration therefore uses
the snapshot delta from that baseline, rather than replaying rewritten history over local fixes.
Only these forks' `master` branches are included. No companion root patcher is shipped or installed.

## DisplayPort recovery candidate

Merged `fix/displayport-retrain` at `c33c5db`. `-NRedDPFix` opts into receiver pre-wake and a
20-second transmitter BIOS branch-loop deadline for the inspected Renoir / Sonoma `23J631`
framebuffer. The earlier receiver-only candidate failed monitor power-button recovery; this
version still needs hardware verification. Other images leave the recovery hook uninstalled.
See [DisplayPort-Recovery.md](DisplayPort-Recovery.md) for scope, evidence and diagnostic markers.

## Rendering behavior and integration decisions

GLFIX remains opt-in. OS-specific exact pages are primary. A version/APU match alone no longer stops
semantic scanning: it stops after an exact rendering page is applied. The explicit semantic QA override
remains available. The signature resolver remains the final fallback, following this combined fork's
existing policy; xiaot-evo's removal of its unused resolver is not applied over the actively used resolver.
Tahoe retains the gate/allow exact patch, including the second allow-pattern occurrence.

Weachy's native site fallback is included with additional context checks: every original site and the
16 surrounding bytes on each side must match the reference image. This permits unrelated page changes
without identifying a page from a short instruction alone. VDA pages require a ready bridge. Repeated
process pages are still patched; a one-shot diagnostic never suppresses subsequent patching. Resolver-only
QA still skips rendering-page and semantic patches. Already-patched exact pages retain the fast path.

Metal SubmitGuard is enabled by default on Darwin 23/24/25, independently of GLFIX/VDA. It verifies the
known method prologue, installs the upstream PM4 tail-filler payload and publishes IORegistry markers.
`-NRedNoSubmitGuard` opts out. The PM4 compute submission vtable overwrite is paused, matching both
upstreams' Quick Look/Metal hang investigation. Neither change is hardware-validated in this fork yet.

The 1.0.0 update corrects the shared-region syscall wrapper to forward process, argument and return-value
pointers, and reads the process's shared-cache base before applying SubmitGuard. Its new LegacyBlend
patch runs from that SubmitGuard path, independently of GLFIX, using Darwin-specific offsets and opcode
checks to address Metal dropdown rendering. `-NRedNoSubmitGuard` disables both. LegacyBlend is skipped
when the SubmitGuard path returns early, including when SubmitGuard is already installed. The existing
GLFIX exact-page, semantic and signature paths remain available. FairPlay-entitled tasks now skip VDA
patches in both the exact-page and contextual-site paths. These changes require hardware validation.

## Boot arguments

| Argument | Effect |
| --- | --- |
| `-NRedGLFix` | Enable exact rendering pages, contextual site fallback and automatic semantic/signature fallback |
| `-NRedGLFixOff` | Disable rendering fixes; overrides GLFix |
| `-NRedGLFixSemanticMTL` | Force semantic GL/Metal scanning, including after exact pages apply |
| `-NRedGLFixSemanticOff` | Disable semantic matching; overrides the force flag |
| `-NRedGLFixResolveOff` / `-NRedGLFixNoResolve` | Disable signature fallback |
| `-NRedGLFixResolve` | Legacy redundant flag; resolver already follows GLFIX |
| `-NRedGLFixResolveOnly` | Signature-only rendering QA; VDA exact pages remain available |
| `-NRedVDA` | Request experimental H.264 and HEVC video acceleration |
| `-NRedAVC` | Disable HEVC decode and encode capabilities; overrides the other video modes |
| `-NRedAVCEncode` | H.264 hardware decode, software HEVC decode, preserve HEVC hardware encode |
| `-NRedVCNNoGfxOff` | Optional GFXOFF hold when a video mode is requested |
| `-NRedForceVDA` | Override the external AMD GPU block |
| `-NRedNoSubmitGuard` | Disable the otherwise-default Metal SubmitGuard and its LegacyBlend path |
| `-NRedDPFix` | Opt into the guarded DisplayPort recovery candidate on the inspected Renoir/Sonoma build |

Keep unrelated boot arguments. Use one video mode; existing `-NRedGLFix -NRedVDA` remains supported.
The standard NootedRed switches remain available. Hardware encoding still needs output validation.

## Video compatibility

Exact variants are Sonoma `23J631`, Sequoia `24H32` and Tahoe `25G241`. Declared family fallbacks cover
`23G`/`23H`/`23J`, `24G`/`24H`, and `25G`, respectively, with Darwin minor 6. Every ABI guard/getter and
original call-site byte is verified before writes. Empty or unrelated builds stay inert. Exact variants
have priority. The per-build VCN architecture is retained; the duplicate legacy Tahoe kernel header is
replaced by `VCNData/25G241.hpp`.

Eligible APUs remain VCN2 (`1636`, `1638`, `164C`, `15E7`). NVIDIA or other non-AMD discrete GPUs no
longer block video acceleration; an external AMD GPU still blocks it unless explicitly overridden.
A kernel-family match is not proof that VA/AppleGVA page contexts match or that decoding/encoding works.
See [COMPATIBILITY.md](COMPATIBILITY.md) for the feature matrix.

`NRedVCNDataVariant` IDs: 1=`23J631`, 2=`24H32`, 3=`25G241`, 4=`23H`, 5=`23G`, 6=`23J`, 7=`24H`,
8=`25G`, 9=`24G`. Family adapters carry no local kernel identity. Identity availability is provenance,
not a fresh runtime UUID/SHA check.

## Tools and verification

The Firefox/Zen launcher is documented in
[README-firefox-hwdecode-launcher.md](../tools/README-firefox-hwdecode-launcher.md). It disables the
browser instance's RDD media sandbox and optionally changes profile hardware-decoding preferences.
VCN generation retains the variant format and supports `--root`/`--darwin` for offline data. VA/GVA
imports include Tahoe generation support. Hardware scripts recognize all three video modes and keep
HEVC decode and encode checks separate.

The compatibility collector detects the macOS version and creates `nred-compat-<version>` beneath
`--out` (the current directory by default). An explicit output name beginning with `nred-compat` is
also accepted. ZIP names retain the complete version string, including all dots.

Run the host checks:

```sh
python3 tools/test_patch_data.py
python3 tools/test_patchset_selection.py
python3 tools/test_gl_semantic_data.py
python3 tools/test_patch_dispatch.py
python3 tools/test_vcn_multibuild.py
python3 tools/test_video_modes.py
python3 tools/test_dp_recovery.py
python3 tools/test_atom_loop_guard.py
python3 tools/test_atom_native_vm.py
```

The compiled checks require a C++ compiler (`CXX` may override it). They execute production option parsing,
dispatch and VCN selection with kernel services stubbed. CI runs these checks on the existing macOS
release workflow. The native ATOM VM test requires the inspected stock macOS framebuffer and skips
when it is unavailable. On a Mac with AppleForge, build with:

```sh
xmake f -m release -a x86_64 -y
sh tools/build-branch.sh -y
```

Artifacts remain under `build/branches/<sanitized-branch>/macosx/x86_64/release/`, with timestamped ZIPs.
The 1.0.0 integration was checked on macOS with host regression tests. A kext build remains pending:
this checkout's host lacks full Xcode, xmake and AppleForge. SubmitGuard installation, boot, rendering,
playback, encode output and sleep/wake checks also remain pending. No kext was installed or deployed.

Local Renoir `0x1636` / Sonoma `23J631` 0.9.1 tests found compute hangs with GLFIX+VDA, GLFIX only, and
both disabled. Earlier 0.9.0 short decode probes passed but encoding produced incorrect pixels. The new
hang-related changes require fresh hardware tests before claiming that those failures are fixed.

## Future updates

```sh
git fetch upstream master
git fetch xiaot-evo master
git merge upstream/master
git merge xiaot-evo/master
```

Resolve overlaps against this combined behavior, retain compiler/CI fixes, and run the checks. If a
source is rewritten, compare old/new snapshots before merging. `origin` remains your own repository.
