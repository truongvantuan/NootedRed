# Weachy October 27 / 1.2.0 integration

Upstream: `b079c4edb68d4edf94cee6e7ec5c1715cff8901b` (27 October 2026).
Local pre-integration checkpoint: `e8449e543b2b0a420c59bd6c601eba7e86606548`.
A source snapshot, original diff, Git bundle and upstream delta are preserved
under `build/weachy-1.2.0-20261028/`; backup branch
`backup/pre-weachy-1.2.0-20261028` retains every earlier local commit plus the
previously uncommitted 24H232 fixes and diagnostics. No remote push occurs.

## Review and merge decisions

| Upstream commit | Change | Local integration |
|---|---|---|
| 35d04ef | VA tables and generator updates for Darwin 22–25; pitch correction | Import the new tables and generator improvements. Preserve exact-page checks; correct the Sequoia/Tahoe pitch fallback to our complete tested 37-byte instruction sequence. |
| 4c4f142 | Default-on GLFix/VDA with NoGLFix/NoVDA/NoHEVC arguments | Adopt defaults through one shared video-policy helper. Keep legacy AVC/AVCEncode modes and existing GLFixOff alias, with opt-outs taking priority. |
| 83463c3 | Resolver architecture/roadmap | Preserve as upstream reference, clearly distinguish its unverified claims from local behavior. |
| d95aa09 | Version 1.2.0 | Update xmake and Xcode bundle versions. |
| b079c4e | VDA signature resolver and original-site matching | Import signature data and a bounded, transactional page planner. Put the runtime fallback behind explicit -NRedVDAResolve; default EFI does not enable it. |

The upstream Main10-default change is intentionally not adopted. The local
`-NRedHEVC10` opt-in and Profile 2 decode-level guard remain because earlier
VCN hangs make automatic Main10 enablement an unjustified regression risk.
`-NRedNoHEVC` disables HEVC decode and encode while keeping AVC; legacy
`-NRedAVCEncode` keeps HEVC encode but disables HEVC decode. `-NRedNoVDA`
disables the bridge/user-patch request and strips media capabilities from both
the existing matched dictionary and injected personalities. No flags are
silently interpreted differently in the three VDA entry points.

The new upstream encoder fallback selected 32 bytes before a divide opcode.
On the Sequoia/Tahoe reference that includes seven preceding bytes from vector
initialization/store instructions. Our correction starts at the actual pitch
calculation, preserves the preceding instructions, divides texture byte stride
by element size and keeps the native chroma relationship. CPU instruction tests
cover 45 width/element/alignment combinations. The old separate Sequoia pitch
registration is removed to avoid overlapping/double patching; the updated exact
table owns that same tested replacement. The generator's fallback now requires
the complete known instruction block rather than an arbitrary preceding window.

## Resolver limits

The imported signature algorithm does not provide whole-driver attestation.
Several contexts are short, counters were global to a boot, and the upstream
implementation could stop after its first match without establishing uniqueness.
Our page planner rejects out-of-bounds/overflow, wrong-site, ambiguous and
intersecting records before writing. It re-plans under the write lock, refuses
the shared cache and all other paths, respects the bridge/FairPlay gates, and
never suppresses later page validations with global application counters.
Failure to restore write protection is fatal rather than silently continuing.
Source-pitch signatures are excluded; exact-page data owns that correction.

This remains an experimental standalone-driver QA path, not a claim of safe
automatic adaptation to every unknown driver or shared-cache build. It is
**not added to this machine's EFI arguments**. Existing full-page VA/GVA tables
remain the production path. The bundled Sequoia VA data identifies 24H32;
24H232 video compatibility is not inferred from enabled flags or kernel bridge
readiness. Do not bypass those references to claim hardware media validation.

## Local work preserved

The 24H232 shared-cache UUID and complete-page Metal correction, per-process
SubmitGuard/LegacyBlend safety, NotificationCenter exclusion, page-local OpenGL
owner/relocation planner, GL budget correction, multi-build VCN registry and byte
checks, bounded VCN drain, GfxOff workaround and VM/allocation/context diagnostics
are retained. Old upstream fixed-kernel-header changes are reconciled into our
existing versioned registry instead of adding a competing selector. Previous
Riot/Zalo diagnostic tools and local source history are preserved.

## Validation and installation

The regression workflow includes 34 host checks, including new resolver and
capability-policy tests. They exercise production code with sanitizer shims;
no graphics/video workload, application launch, sleep or reboot is part of
these tests. Source verification and build provenance are recorded beside the
artifacts. RELEASE is the EFI artifact; DEBUG is built separately for diagnosis.
Build/test checks do not prove runtime compatibility on this new kext.

The authorised installation replaces only NootedRed after a full internal-EFI
backup and byte comparison. Existing boot arguments, the Bluetooth board-ID
fix, Phantom r2, wireless root patches, USB map and audio settings are preserved.
A manual reboot and passive capture are required before controlled workload
checks. Bluetooth shutdown/power-on endurance remains a separate pending test.

Upstream source:
- https://github.com/weachy/NootedRed/commit/35d04ef
- https://github.com/weachy/NootedRed/commit/4c4f142
- https://github.com/weachy/NootedRed/commit/b079c4e
