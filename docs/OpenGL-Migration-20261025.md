# Conditional OpenGL migration RELEASE candidate

Migrated the SE/CU and conditional DualQuad work from
[steve12311 commit f8179e5cb03a17162c5a97b3df2e9d56cb8b62e1](https://github.com/steve12311/NootedRed/commit/f8179e5cb03a17162c5a97b3df2e9d56cb8b62e1).
The RELEASE candidate has now booted and passed all seven native graphics/media
output cases. Actual system sleep/wake is still pending; see the runtime evidence below.

## Integration

`UserPatches` remains the only owner of `_cs_validate_page` and
`_cs_validate_range`. `UserOpenGL` is a planner/writer invoked through those
existing hooks; it registers no additional hook or startup file-reading task.
The original generated pages and all 48 byte arrays match the pinned fork.
Only the small relocation/type subset needed by the GL planner was imported;
the fork's shared-cache, SRD/scratch and FairPlay frameworks were not added.

On Darwin 23/24/25, with our existing GL enable/profile gates satisfied, the
complete-block planner exclusively owns the SE/CU and DualQuad targets.
After its rejection, the driver page cannot fall back to the old short-opcode
exact/context/semantic patches. Native-table construction also excludes those
old records for this owner. A GL-only configuration can install the hooks even
when it has no other native page records.

`-NRedGLFix` enables it; `-NRedGLFixOff` retains precedence. Existing resolver-only
QA uses the complete-block dynamic path and suppresses the exact budget patch.
Dynamic matching is disabled when both existing resolver and semantic controls
are disabled. No `-NRedDisplayFix` argument is needed or implemented as an alias.

The separate exact Sequoia `0x5000` budget correction remains, including its
conditional zero-budget behavior. The budget payload, encoder pitch payload,
VCN bridge and existing SubmitGuard/LegacyBlend installers are unchanged.
GL diagnostics, including budget success, publish asynchronously outside the
validation/write-lock path. Unknown/ambiguous/cross-page blocks fail closed.

Validation wrappers preserve native results and outputs, accept page success
`1`/`0xF`, reject taint/NX and misalignment, and protect range arithmetic.
The 32 MiB GL-file bound is not imposed on large shared-cache offsets used by
Metal/VA. Range validation identifies a GL vnode as a standalone file so the
new planner also works through that entry point.

The verifier recognizes per-device conditional pages separately from older
short-opcode builds. Candidate deployment metadata requires revision 5,
the page-local owner, enable property and a valid native backend before GPU
workloads. Missing/unknown device identity cannot select an unverified page.

## Checks

All 24 CI build/regression checks pass. This includes generated-data
reproducibility, all previous patch/media/guard tests and the new GL tests:

- 1,236,096 native CPU cases: SE/CU arithmetic, PCI/branch isolation, conditional
  DualQuad and native packet behavior across three OS profiles and six APUs.
- 295,272 sanitized page-local resolver cases; a separate run with the verified
  local Sequoia reference passes 295,290 cases including full-page checks for
  all six device variants.
- 293 actual planner/writer cases with sanitizers: races, write failures,
  restoration retry/failure, repeat validation, async diagnostics, exact-only
  and resolver-only policy, and budget reporting.
- 545 actual combined validation-wrapper cases with sanitizers: native argument
  forwarding/results, validation bitmap, taint/NX/nulls, alignment/overflow,
  GL range identity and large VDA cache offsets.
- Combined-owner regression: NotificationCenter/unrelated vnodes stay untouched,
  new GL rejection cannot use the old fallback, and the exact budget fix retains
  its device-name/page/QA restrictions.

Final RELEASE object prologues stay within their checked stack budgets:
page/range validation entries use 72/56 bytes before the first call; GL patch
worker 584 bytes; resolver 120 bytes; shared-region entry 24 bytes.
These exclude return addresses, callers and deeper frames and are not a claim
about the complete kernel-stack peak.

After the last native-table guard refinement, the affected patch-data,
dispatch and combined guard checks were repeated successfully. The final
verifier gate and sanitizer suites also pass. No GPU rendering workload was
submitted by these source tests.

## Artifact and next verification

- RELEASE UUID: `E1FB4DBA-884F-352D-AD6E-20996871793C`
- Executable SHA256: `d1fc9782f9b496e0986fe595bf26feb0a2a262b8fa85a2dae079df5afcfad6db`
- Kext: `build/branches/opengl-page-local-20261025/macosx/x86_64/release/NootedRed.kext`
- ZIP: `NootedRed-1.0.0-RELEASE-20261025-205357.zip` in the same directory

The ZIP passes integrity checks and contains the exact verified executable.
`build/fork-audit/opengl-migration-20261025/ARTIFACT.json` records bundle/archive
hashes; that directory also contains before-images, source delta, test results,
compiled stack checks and the candidate feature-verifier identity.

The migration/build did not change EFI/config/boot-argument files. The user
subsequently installed the bundle as recorded below. Keep the currently working
bundle as rollback. After installing the candidate and rebooting, verify its
UUID, three full GL pages, intact NotificationCenter pages, the seven native
graphics/media cases and actual system sleep/wake with device operation.
Sleep/wake, long-duration stability and any performance change remain unverified.

## First migrated-build boot

Boot `863B0DFE-8562-478D-B708-ACD0A08AAB50` loaded RELEASE UUID
`E1FB4DBA-884F-352D-AD6E-20996871793C` after the user installed it. The
internal EFI bundle and other expected profile files match. Revision 5, both
validation backends, SE, conditional DualQuad and the budget correction are
active; no GL write or permission-restoration error was reported. The exact
page path was selected (`DynamicApplied=0`), which is expected on this reference.

All seven native Metal/GL/video output cases pass. All three complete GL pages,
Metal/VA patch pages and SubmitGuard payload/entry/continuation match; the
payload's current and maximum permissions are RX. NotificationCenter's 904
checked code pages remain valid. No GPU reset/hang or retained allocation/resolver
warning was observed in the captures. All 15 executable kexts and three live
USB maps match, and the ACPI GPE repair loads without the queried name/table
errors. The user confirmed normal desktop/menus, usual USB ports, speaker and
Wi-Fi before the workloads.

Physical post-test confirmation and an actual system sleep/wake are still pending.
Evidence is under `build/fork-audit/opengl-migration-20261025/boot-20261025-211514/`.
No EFI writes or sleep request were performed during this verification.
