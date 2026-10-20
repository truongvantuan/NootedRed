# Cross-build semantic GL/Metal patches (Plan B)

Status: implemented in `master` (2026-10-20), build-verified and validated offline against the macOS 14,
15.8.1 and 26.7.1 driver images. Not yet runtime-tested on hardware beyond the existing 15.8.1 build.

## Problem

The exact-page backend (`PatchSet`/`PagePatch`) is keyed by the whole 4 KiB page image and a fixed
`find`/`skip`/`count`. That is the safest mechanism (L0 in
[`docs/Compatibility-Architecture.md`](../docs/Compatibility-Architecture.md#47-verification-ladder))
but it needs a new page snapshot plus offsets for every macOS build. The Chromium/GL sites are small,
well-understood instruction sequences, so the same fix can be located by semantics instead.

The semantic backend adds a second mechanism:

- `NootedRed/UserPatches.cpp` matches masked instruction-context windows on the page being validated;
- `NootedRed/GLFixSemanticData.hpp` stores the contexts, masks, site offsets and same-length replacements;
- `tools/test_gl_semantic_data.py` validates the data against the available driver images and page
  fixtures.

There is no page snapshot in the semantic path: the context window is ~40–64 bytes and the write only
happens after the expected `find` bytes and the instruction form are verified. Ambiguity is a no-op.

## Sites and how they were derived

### GL driver (`_gfx9_HwInfoInitData`, `_glrAMD_GFX9_UpdateHwCbDualQuadMode`)

The two GL sites are the ones validated in `analysis/gl-hwinfo.md`:

- A1: `rec+0x78 = 4` in the Vega10 branch, replaced with `1` (the iGPU has one shader engine);
- A2: `and eax, ~1` in the dual-quad update, replaced with `or eax, 1`.

The contexts were extracted from the stock 15.8.1 driver (the live file is page-cache patched, so the
collector reconstructs the two pages from the committed arrays). They were then byte-for-byte
compared with:

- macOS 26.7.1 `AMDRadeonX5000GLDriver` from `platform-data/2026-10-19_macos-26.7.1_*`;
- the macOS 14 (Sonoma), 15 (Sequoia) and 26 (Tahoe) page fixtures in
  [`weachy/NootedRed`](https://github.com/weachy/NootedRed) (`UserPatchesSonoma.inc`,
  `UserPatchesSequoia.inc`, `UserPatchesTahoe.inc`).

Result: the A1 window differs only in the RIP displacement bytes (wildcarded, three bytes in the mask);
the 64-byte A2 window is identical across all five versions. Both contexts match exactly one site in
every tested driver/page.

### Metal variants

Apple's Metal driver is in the dyld shared cache, so the runtime cannot key it by a bundle path from the
code-signing page hook. Instead the data stores **variant groups**:

| group | build | sites | notes |
| --- | --- | --- | --- |
| 1 | macOS 14 Sonoma | gate `75 0B` + allow `0F 93 C0` | from the Sonoma page fixture |
| 2 | macOS 15 Sequoia (15.8.1) | gate `75 0B` + allow `0F 94 C0` | validated on the 15.8.1 image |
| 4 | macOS 26 Tahoe direct-field | `83 E2 FE` → `83 CA 01` at `+0xE4` | from `weachy/NootedRed` `TahoePatchData.hpp`; verified in the 26.7.1 MTL image |
| 3 | macOS 26 Tahoe gate/allow | gate `74 28` + allow `0F 94 C1` | fallback for 26.x pages without the direct form |

A group only applies when **every** site in it matches the same page, and at most one group applies per
page (the direct-field group is ordered first so a 26.x page takes only that variant). This makes a
partial or foreign cache page a no-op.  Metal scanning is enabled automatically when no exact patch set
matches the running build; on a build with a patch set it is forced on with `-NRedGLFixSemanticMTL` because
the shared-cache range hook processes much more data than the GL bundle pages.

## Runtime behaviour

- The semantic GL fallback is enabled together with `-NRedGLFix` (exact page sets still run first); it
  is disabled with `-NRedGLFixSemanticOff`.
- GL entries only patch a file-backed page whose vnode name contains `AMDRadeonX5000GLDriver`. The name
  lookup happens only after a context candidate was found, so it is not on the hot path for every page.
- Metal group scanning is enabled automatically on builds with no exact patch set (and can be forced with
  `-NRedGLFixSemanticMTL`); `-NRedGLFixSemanticOff` disables the whole semantic backend.
- Success is published as `NRedGLFixSemantic=1` / `NRedGLFixSemanticMetal=1` and logged under the
  `UserPatch` tag.
- Any failed verification (no match, more than one match, wrong `find` bytes, wrong instruction form)
  results in no write.

## Validation

```sh
xmake -y
python3 tools/test_gl_semantic_data.py \
    --reference-repo /path/to/weachy/NootedRed \
    --collector-dir /path/to/collect_compat_data/output
```

The test reconstructs the stock 15.8.1 GL driver from the committed page arrays and additionally checks
the 26.7.1 driver images and the Sonoma/Tahoe page fixtures. It verifies structure, uniqueness, the
site's `find` bytes and the group behaviour. Expected coverage after the run:

```
GL: 15.8.1, 26.7.1, Sonoma, Sequoia, Tahoe
MTL: 15.8.1 (group 2), 26.7.1 (groups 3/4), Sonoma/Sequoia/Tahoe page fixtures
```

## Limitations

- The GL contexts are still build-derived data: a future compiler refactor can change the surrounding
  instructions and turn the semantic fallback into a no-op. That is intentional (fail-closed), and the
  fix is to collect the new driver and update the context/mask, not to guess.
- The Metal variants are per known build; a new macOS release needs a new context pair (or the direct
  form) derived from its MTL image. Only the 15.8.1 Sequoia group has hardware validation.
- No hardware validation was performed for the semantic path itself. It uses the same page-write
  mechanism as the validated exact-page path, but the first boot with it should still be treated as
  experimental (`-NRedGLFix` is the opt-in already).
- The semantic path does not replace the exact-page tables for known builds; those stay the L0 fast path.

## Extending

1. Run `tools/collect_compat_data.py` on the new build (pristine boot preferred) and keep the resulting
   `chromium/` data.
2. For GL: the collector's `sites.json` shows the A1/A2 hits; update the context/mask in
   `GLFixSemanticData.hpp` if the window changed.
3. For Metal: add a new variant group from the MTL image / reference page fixture, then extend
   `tools/test_gl_semantic_data.py` with the new corpus.
4. Rebuild and run the test; do not rely on a matching context alone without the test.
