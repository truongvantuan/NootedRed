# New OpenGL commit review

Pinned commit: [f8179e5cb03a17162c5a97b3df2e9d56cb8b62e1](https://github.com/steve12311/NootedRed/commit/f8179e5cb03a17162c5a97b3df2e9d56cb8b62e1),
the single new commit after the `ac1a08e` review. It changes 19 files, adding
3,677 lines and removing one. Runtime code was not merged or installed.

## What changes

- Adds a standalone `UserOpenGL` module behind the fork's `-NRedDisplayFix` flag,
  covering Darwin 23/24/25 and six Vega APU identities, including our 1002:1636.
- Replaces a complete 256-byte shader-engine repair block. It handles all three
  valid Vega branches, changes shader-engine count to one only for the selected
  iGPU, and preserves native CU multiplication, invalid revision behavior and
  unrelated devices/fields.
- Replaces the 142-byte DualQuad function. It sets `DISABLE_DUAL_QUAD` for the
  selected iGPU only when dual-source blending is active. Normal drawing and
  unrelated GPU capability handling retain native behavior.
- Applies changes only after native code validation. Exact reference pages have
  a fast path; otherwise a page-local resolver compares the full repair blocks,
  checks known relative targets, rebuilds displacements, and rejects ambiguity,
  unknown bytes and blocks crossing the page boundary. It neither reads adjacent
  pages nor claims global uniqueness or arbitrary unknown-ABI compatibility.
- Restricts page validation success to boolean 1 or XNU's whole-page bitmap 0xF,
  requires untainted/executable page results and aligned/bounded file offsets,
  and preserves original outputs. Our existing nonzero check already accepts
  0xF; the missing improvement is stricter rejection, not first-time bitmap support.
- Uses small noinline entry frames, no heap allocation or file I/O in the page-in
  path, and asynchronous atomic diagnostics after matches/errors. Diagnostic
  registration at startup does not schedule patch-preparation work.

## Difference from our running build

Our current RELEASE already corrects one shader-engine immediate and changes
`and eax, ~1` to `or eax, 1` at the DualQuad site. The latter forces the disable
bit more broadly. The new fork offers better device/branch/draw-mode isolation
and larger matching contexts. These are credible correctness and compatibility
candidates, not a measured speed improvement on our machine.

Both implementations patch the same GL driver pages, `0x8000` and `0xE000`.
They must not run as independent competing owners. A future migration should
adapt the conditional planner/payloads into our existing guarded module and
coordinate its exact, semantic and resolver paths. Preserve our unrelated-vnode
rejection, boot-argument precedence and independent Metal/VCN policy.

This commit does not include our `0x5000` zero-resource-budget correction for
512 MiB hardware. Preserve that conditional correction. Our present 1536 MiB
configuration has a positive native budget, but other supported configurations
still need the fix. This commit does not increase VRAM or change VCN encode/decode.
Do not add the fork's display flag to our EFI as though it were an implemented alias.

## Checks performed

Pinned source was tested in an isolated worktree:

- Generated OpenGL data reproduces exactly for three OS profiles and six APUs.
- Native CPU payload tests pass 1,236,096 cases, including PCI/branch isolation,
  CU arithmetic, conditional DualQuad and native packet submission behavior.
- Actual hook harness passes 1,379 sanitized cases for validation ABI/results,
  patch races, restoration failures and enable/disable policy.
- Page-local resolver passes 295,290 sanitized cases and read-only checks against
  a local Sequoia reference copy for all six device variants.
- The hook harness stack check passes. The fork's separate linked-kext/link-map
  stack-budget tool was not run; no complete kernel-stack peak is claimed.

The original dynamic runner hardcodes Darwin 25 for the current system and
Darwin 24 for `/Volumes/Macintosh SSD`; that invocation asserts on this Darwin 24
host. The same compiled resolver harness passes when given the correct local
Sequoia reference. In that local copy only, our two existing patch sites were
normalized to stock; both complete 4 KiB page hashes then match the pinned fork.
No host driver bytes were changed. This is reference/CPU evidence, not a GPU boot
test of the new module.

Evidence: `build/fork-audit/opengl-review-20261025/`. Our installed safety RELEASE
remains `0B6AEF80-BA7B-3155-8F57-519765032FB1`; it separately passed seven native
GPU/media cases. Its system sleep/wake test is deferred at the user's request.
