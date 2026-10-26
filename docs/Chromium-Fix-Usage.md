# Chromium / Electron fix: current fork notes

The conditional GL resource-list budget correction is now boot-verified on this
512 MiB machine. Native GL passes, Zen reports WebRender, and Brave passes hardware
WebGL 1/2 readbacks. See [GL-Zero-Budget.md](GL-Zero-Budget.md) for evidence and limits.

The original guide moved to [archive/Chromium-Fix-Usage.md](archive/Chromium-Fix-Usage.md)
in commit `a246939`. Its reported validation was NootedRed 0.9.0, macOS 15.8.1 / 24H32,
GL driver 7.0.25 and APU `0x1638`. It does not establish success on this machine's `0x1636`.
Use [the current feature verification](Weachy-Feature-Verification.md) for this combined fork's results.

## Setup and flags

Keep NootedRed enabled after Lilu in OpenCore. Use `-NRedGLFix`; `-NRedGLFixOff` overrides it.
Avoid a second GL/Metal patcher such as BFixup or WhateverGreen. Preserve a verified EFI backup.

This fork enables signature fallback with GLFix unless explicitly disabled. The archived
`-NRedGLFixResolve` recommendation does not add a missing fix when both exact GL pages already match.
`-NRedGLFixResolveOnly` is a diagnostic mode, and forcing `-NRedGLFixSemanticMTL` is unnecessary for
the verified exact pages. Video acceleration is a separate feature with separate boot arguments.

## What is implemented and verified

| Guide requirement | Current evidence on Renoir `0x1636`, 24H32 |
| --- | --- |
| Enable GL shader-engine correction | `-NRedGLFix` active; complete intended patched `0xe000` page verified. |
| Disable GL dual-quad | Complete intended patched `0x8000` page verified. |
| Correct the zero resource-list budget at 512 MiB | Exact-only `0x5000` page verified; the formerly missing sync resource is now mapped. |
| Preserve conditional Metal behavior | Corrected cache bytes verified; opaque, alpha and dual-source pixel tests passed on the earlier rendering-repair boot. |
| Load after Lilu without another graphics patcher | EFI ordering verified; loaded Lilu 1.7.3; no BFixup or WhateverGreen loaded. |
| Render correctly without a new GPU reset | **Passed on the 13:08 boot**: four native GL cases twice, Zen WebRender reported by the user, and Brave WebGL 1/2 pixel checks; zero observed resets. |

The earlier solid-color failure preceded the dual-source test despite the original guide's
patches being present. Investigation found an additional inherited Apple GL calculation that
produces a zero resource-list budget at 512 MiB. Correcting that calculation resolves the native
reproducer. Adding launcher flags alone did not correct it. Broader workloads and sustained
stability still require observation; browser feature labels alone do not verify video or WebGPU.

## Reliable page verification

A plain file mapping can show stock bytes before the loader registers the file's embedded signing
blob. The collector now registers the driver's existing embedded signature with the kernel, then
reads its executable mappings. It does not replace the signature, run driver initializers, call GL
or write system files. This allows the installed signing-validation hook to run before GPU testing.
See Apple's [fcntl definitions](https://github.com/apple/darwin-xnu/blob/main/bsd/sys/fcntl.h)
for `F_ADDFILESIGS_RETURN` and its existing-file signature semantics.

On this boot, the initial stock-page result became two full patched-page matches after that step,
with `NRedGLFixGLApplied=1` and zero GPU work. It was a collector preparation issue.

The optional render probe submits actual GPU work. Following a failed draw or reset, collect the
evidence and investigate before another exercise. The successful comparison and its preceding
fault/mapping evidence are linked from `build/gl-zero-budget-20261023/RUNTIME-PASS.json`
and [GL-Zero-Budget.md](GL-Zero-Budget.md).
