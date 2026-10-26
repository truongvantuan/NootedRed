# GL resource-list budget on 512 MiB hardware

The 24H32 Apple GL driver computes a zero resource-list budget when its device-info
input reports 512 MiB. The conditional correction now passes the formerly failing
native GL test on this machine: the missing sync resource is mapped, all four pixel
cases pass, and no reset is observed. Zen reports WebRender. This verifies the original
reproducer; it does not establish every workload or long-term stability.

## Evidence

The 12:26 boot uses diagnostic v2, UUID `B4D2EC51-AD47-3C3B-9132-4BDF0D899529`,
with both intended GL pages and private Metal patches verified. One bounded GL test
fails its first solid-color case and records one reset. The user confirms a responsive
desktop afterward; further GPU work on that boot stopped.

The API capture records allocator response sequence 13 returning GPU address
`0x400001000`, size `0x1000`, to probe PID 1027. Six saved snapshots contain the same
219-packet IB prefix. WRITE_DATA at byte `0xc24` targets that exact address. The GPU
reports a CPG write fault there, VMID 10, with VALID/WRITE labels. None of the six
observed native mapping ranges contains this page; initialization, worker-thread and
other unobserved paths remain a coverage limitation.

The ring's INDIRECT_BUFFER packet is `c0023f00 00060000 00000004 0a0004a0`.
Its length field is in dwords, consistent with [AMD's GFX9 packet emitter](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/gfx_v9_0.c):
`0x4a0` means `0x1280` bytes. Treating it as a byte length truncates an instruction;
the decoder rejects that shorter extent. The complete supplied extent has one memory
WRITE_DATA packet. This identifies submitted work, without proving causation from an
opcode alone.

Read-only device-info selector `0x100` returns `536870912` at offset `0xe0`.
`gfx9_HwInfoInitData` shifts that value right by 20 and stores 512 at hardware-info
offset `0x14`. `AMDRsrcList_Init` then computes:

```text
budget_KiB = (VRAM_MiB << 10) - 0x80000
           = (512 * 1024) - 524288
           = 0
```

`AMDRsrcList_AddRsrc` rejects an addition when the accumulated resident KiB exceeds
that budget. `IOAccelResourceCreate` initializes the resident-size value from allocation
response offset `0x28`; `IOAccelResourceGetResidentDataSize` reads that value. The
captured response contains 4096, so the initial nonempty resource cannot fit this list.
This arithmetic is in the inherited Apple GL binary; the earlier Weachy GL patches
do not change it. No missing launcher flag or omitted merge is required to explain it.

## Correction and guards

`UserPatchesGLBudget.inc` replaces the 50-byte initializer only when the complete
signed 24H32 page at file offset `0x5000` matches. The driver UUID used for the reference
is `BAD9208B-B99B-3DAA-AA51-15D199498873`; its original page matches the embedded
CodeDirectory hash. The exact executable vnode name is required. No contextual,
signature or semantic fallback is registered for this function replacement.

The replacement supplies `0x40000` KiB (256 MiB) only when the native computed budget
is zero. Every nonzero result retains the original arithmetic, including the native
behavior for unsupported smaller memory sizes. The fixed 256 MiB limit is a bounded
initial choice for this 512 MiB machine; broader workload stability remains to be measured.
It does not change the reported VRAM, BIOS reservation, GPU addresses or PTE permissions,
and it does not immediately allocate or reserve 256 MiB of physical memory.

The initializer's operations are:

```asm
pushq %rbp
movq %rsp, %rbp
pushq %rdi
xorl %eax, %eax
pushq $5
popq %rcx
rep stosq                 # zero exactly the original 40-byte object
popq %rdi
movq %rsi, 0x10(%rdi)     # preserve context
movq 0x12d8(%rsi), %rax
movl 0x14(%rax), %eax
shll $10, %eax
addl $-0x80000, %eax
jnz done
movl $0x40000, %eax
done:
movl %eax, 0x20(%rdi)
popq %rbp
retq
```

The 48-byte function is padded with two NOPs. The frame pointer and RDI are preserved;
RCX is caller-saved. No trampoline or external call is added.

## Verification and remaining work

`python3 tools/test_gl_budget.py` executes the production initializer bytes and a copy
of the native add-resource routine with its three external calls rebound to CPU stubs.
The stock 512 MiB case rejects 4 KiB; the replacement accepts/retains it. Nonzero
budgets, surrounding memory, repeat/dirty references, list capacity and oversized-resource
rejection pass under AddressSanitizer/UBSan. It requires an x86_64 host and reports a
skip elsewhere. The page guard test executes the production matching path and rejects
wrong executables and modified pages even when the function bytes still match.

The post-boot verifier checks the complete third GL page alongside the prior two GL
pages. Acceptance requires the expected kext UUID and all actual patch bytes, a clean
fault baseline, correct native GL readback, and no delayed reset. The optional API
capture can show whether the sync resource now participates in the observed mappings.
Video and physical system sleep/wake remain separate runtime requirements.

## 13:08 boot: runtime comparison

Our DEBUG UUID `D687C8DC-274B-3E38-AF70-0D798EF38460` loads with `-NRedGLFix`.
The verifier checks all three complete GL pages, the private Metal patches and all
904 NotificationCenter code pages. The original video-off profile is retained for
these tests.

- Native GL passes solid red, ordinary alpha, SRC1_COLOR and SRC1_ALPHA with exact
  pixels, both with and without the process-local API observer.
- The observed native map now includes `0x400001000..0x400002000`, size 4096, and
  returns true. This is the resource missing from the failing comparison.
- Metal rendering passes all three cases (maximum channel error 1, tolerance 2),
  and native Metal compute returns 64/64 correct elements.
- Zen runs without the API observer; the user reports **WebRender**. Its supervised
  startup window has no observed GPU fault/reset. A fresh support-text export has
  not been saved, so the compositing result is a user observation.
- Brave/Chromium 156 passes WebGL 1 and 2 clear/triangle readbacks, checking all
  1024 pixels per draw with zero error. Both contexts and browser GPU information
  identify AMD Radeon Renoir through ANGLE Metal. A temporary profile is used.

The bounded tests and delayed captures record zero new GPU resets or GPU/WindowServer
reports. NotificationCenter remains at 0% CPU in the retained capture and its code
pages remain valid. Earlier allocation-warning lines are still recorded; this fix
does not establish that every allocation warning is resolved.

The first private Chromium result incorrectly required a separate `webgl2` feature
status key that Chromium 156 does not return. Offline validation now checks both
actual contexts, renderer/device identity and pixel results. The original result
and correction are retained alongside six negative validation fixtures; no GPU
workload was repeated for this reporting correction.

The user selected Apple menu → Sleep and reported a responsive desktop and WebRender
afterward. However, `pmset` still reports Sleep Count 0 with no matching system-sleep
transition. Full system sleep/wake is therefore **unverified**. The display-idle
assertion from Caffeine alone does not establish why the explicit request failed.

The aggregate evidence is `build/gl-zero-budget-20261023/RUNTIME-PASS.json`. The
next-boot full-video profile is separate under `build/vcn-full-20261023/`; video
acceleration and its GFXOFF hold have not been verified on this running boot.

Private evidence: `build/gl-vm-trace-v2-20261023/GL-api-test-20261023-122803-982/`,
`build/gl-zero-budget-20261023/`, and the feature matrix in
[Weachy-Feature-Verification.md](Weachy-Feature-Verification.md).
