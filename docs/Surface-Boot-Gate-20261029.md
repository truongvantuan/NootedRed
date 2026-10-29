# Surface option initialization and process-time build identity

The first 7ce9282 boot (08:37 on 29 October) loaded the expected RELEASE UUID,
with `-NRedSurfaceFix` and Phantom absent. The passive probe accepted the current
cache reference and leaf RX permissions, but reported native surface bytes.
Both SurfaceFixRequested and SurfaceFixEnabled were zero. No GPU workloads were
submitted, so this is an installation failure, not a rendering pass.

The eligibility policy incorrectly required `osversion == "24H232"` during
`processPatcher`. XNU defines `osversion` as an initially zero-initialized array
and exposes its later value through a writable sysctl. A post-login sysctl value
is not evidence of its value during early kext initialization. The other current
operands match the policy, but the first candidate did not retain each initial
operand; initialization timing is the supported explanation, pending the new
initial-build diagnostics.

The corrected lifecycle prepares callbacks only when the user requests the
surface feature, GL fixes are enabled, and Darwin/device/profile match. This
step never authorizes surface writes. The actual shared-region callback requires
the exact current build before entering SurfaceSafety, which additionally checks
the cache UUID, complete functions, references, permissions and transaction state.
An empty, missing, differently suffixed or unsupported build cannot enter the
surface adapter. Existing SubmitGuard, LegacyBlend and media behavior is retained.
FairPlay exclusion and SubmitGuard-first ordering are unchanged.

SurfaceFixRequested now reports the actual argument independently of eligibility.
InitialBuildMatched/InitialBuildEmpty retain early identity observations;
RuntimeBuildMatched records a later accepted build. Enabled means callbacks were
prepared; only full patch bytes, permissions and functional output establish
acceptance. No new boot argument is needed. The separate experimental codec
ownership path is unchanged and remains disabled in EFI for this isolated test.

Regression coverage executes production initialization and callback methods:
preparation while the build is empty, rejection before exact identity, later
acceptance once identity is available, wrong-build rejection, unchanged control
combinations, and existing adapter rollback/fault cases.

References: [XNU version template](https://github.com/apple-oss-distributions/xnu/blob/main/config/version.c.template),
[XNU build-version sysctl](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sysctl.c).
Evidence: build/surface-boot-gate-20261029/ and the preceding passive capture in
build/steve-metadata-buffer-20261029/boot-20261029-084132/.

All 52 workflow checks passed, including production initialization/callback
coverage and the surface VM rollback/fault matrix. RELEASE builds pass.

The compiled visible direct call chain remains 4,464 bytes, with a 72-byte
wrapper and a 1,592-byte largest reachable frame. Native kernel/indirect
callbacks remain outside this measurement.

Hardware acceptance remains pending a boot of the corrected candidate.
