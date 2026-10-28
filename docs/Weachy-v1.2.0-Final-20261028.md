# Weachy 1.2.0 published release integration

This follows the earlier pre-release integration of `b079c4e`. Upstream
`a8bbb36` and release tag `v1.2.0` include six further commits. Local history
is retained by a normal merge; `backup/pre-weachy-1.2.0-final-20261028`
and `build/weachy-1.2.0-final-20261028/repository-before.bundle` preserve the
starting point. Nothing is pushed remotely.

| Commit | Decision |
|---|---|
| 44e61bd | Import AppleGVA signature data and guarded standalone resolution. Retain exact GVA pages; do not replace production references with broad scanning. |
| 89164ea | Do not enable unrestricted VA scans of shared-cache pages. Existing full-page/owner guards remain. |
| 1abc701 | Retain exact standalone image paths; no substring path matching. |
| 2937725 | Remove Ventura device-ID 0x1638 restriction. Retain VCN2.2 device profile, engine capability, exact OS build and kernel ABI guards. Other APUs remain unverified. |
| 9e7b407 | Import longer OS-specific contexts and status/processor offsets. Keep our complete encoder pitch correction and transactional multi-site planner. Remove synchronous teardown polling, following native stop directly. |
| a8bbb36 | Preserve release notes with explicit local limitations. |

## Resolver and encoder safeguards

`-NRedVDAResolve` remains an optional QA switch, absent from EFI. Its allocation-free
planner supports all declared occurrences on each page, rejects excess/overlapping
matches and wrong original-site bytes, and revalidates under the write lock.
No global counter suppresses later validations. The AppleGVA path is precisely
`/System/Library/PrivateFrameworks/AppleGVA.framework/Versions/A/AppleGVA`;
AMDRadeonVADriver2 uses its exact bundle path. Cache pages and FairPlay clients
are excluded from this experimental route. Original branch displacements must
match exactly even when the search context masks them. Write protection restoration
failure is fatal. This does not provide arbitrary future-build compatibility.

Static VA/GVA pages remain registered. Existing 24H232 Metal/GL fixes, page-local
OpenGL ownership, NotificationCenter exclusion, SubmitGuard and LegacyBlend are
preserved. The known-good encoder pitch replacement remains the exact 37-byte
correction; the upstream 32-byte SourcePitch signature is not registered.
HEVC Main10 remains opt-in with `-NRedHEVC10`. No security relaxation or new
AMFI boot argument is introduced.

## Teardown

The former polling helper could sleep for up to 250 ms in client/accelerator
stop, where caller-held locks may be needed by completion. The new stop hooks
forward immediately to the native implementation and clear accelerator state
only after it returns. Context tracing, GfxOff workaround and kernel ABI guards
remain. Registry markers: `NRedVCNDrainBuild=4`, `NRedVCNNoDrain=1`,
`NRedVCNDrainReady=0`. Legacy `-NRedVCNNoDrain` is redundant. This is a source
improvement, not proof that every earlier hang is fixed.

## Validation and deployment

Host checks exercise multi-site pages, later validations, four AppleGVA signature
families, exact-path/cache gates, original branches and lock restoration under
ASan/UBSan. The teardown test executes both native/bridge callbacks, verifies
single forwarding and cleanup ordering, and disallows polling/sleeping.
Other host regressions and build/deployment manifests are saved under
`build/weachy-1.2.0-final-20261028/`.

Only NootedRed is replaced in the internal EFI after a complete verified backup.
OpenCore config, Bluetooth, Phantom, USB, audio, wireless root patches and boot
arguments remain unchanged. Reboot and runtime workload verification are still
required. The previous boot's passive verification is not validation of this build.

Release: https://github.com/weachy/NootedRed/releases/tag/v1.2.0
