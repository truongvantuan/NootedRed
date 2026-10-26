# Current EFI verification status

A subsequent [device-specific audit](Device-Config-Audit-20261024.md) restores the tested production NootedRed after diagnostic collection and corrects an inactive boot-audio path. That refinement is staged for the next boot; final runtime validation remains pending. The running diagnostic boot and its actual sleep/wake evidence are recorded in [Allocation-Security-20261024.md](Allocation-Security-20261024.md).

24 October update: the isolated GPE namespace repair is verified on the USB.
All seven native cases pass before and after a recorded system sleep/wake;
the user confirms normal devices and automatic Wi-Fi rejoin. RELEASE binaries and
other config values are retained. The current 111-file profile and its checkpoint
are recorded in `build/postinstall-audit-20261024/RUNTIME-PASS.json`; the 110-file
profile below remains the tested rollback baseline. See
[Postinstall-Audit-20261024.md](Postinstall-Audit-20261024.md) for the current log
audit, limitations, exact backup and routine capture command.

OPENCORE now uses the verified RELEASE profile with the isolated GPE repair.
All seven native render/compute/GL/media checks pass before and after a recorded
system sleep/wake, with no observed GPU hang, reset or new GPU/WindowServer report.
The user confirms normal desktop, menus, usual USB ports, PC-speaker sound and
automatic Wi-Fi rejoin. Browser WebGL/video/fullscreen also passed previously on
the same RELEASE graphics/media binaries; the new ACPI test did not rerun it.

See [Validated-Release-20261023.md](Validated-Release-20261023.md) for current
identities, source state, feature evidence, limitations and artifact locations.

| Area | Current result |
| --- | --- |
| Bootloader | OpenCore RELEASE 1.0.9, same-revision verified package; current boot confirmed. |
| Graphics/media | Our NootedRed RELEASE UUID 4D15A2C3; full GL/VDA/GFXOFF profile, exact patch-byte validation and functional tests pass. |
| Config/files | Matching 1.0.9 validator passes; all 111 current verified files match, including uncached USB and checkpoint readback. |
| CPU/kernel patches | 8 physical/16 logical cores, core immediate 8, one active PAT variant, saved AMD reference definitions match. |
| Kexts | All enabled file references exist, configured dependency order is valid, all 15 executable kexts link offline. |
| ACPI/USB | Native SysReport and active AML reviewed; GPE0MUX loads without the target namespace errors, and normal devices/system sleep/wake pass. |
| Device properties | Native DSDT/gfxutil root 1 confirmed; current Ethernet/NVMe/audio paths match. |
| Audio | Damaged AppleALC executable restored; loading, enumeration and physical speaker playback confirmed. |
| Network | Wi-Fi works and automatically rejoined in this profile's observed sleep/wake cycle. Bluetooth is deferred by user request. |
| Recovery | Failed audit preserved; current files and tested EFI backup recorded; read-only collector retained. |

## Withdrawn audit

The later OpenCore DEBUG/logging switch and EC/APFS refinements were deployed
together and caused a reported pre-macOS hang. Static validation did not prove
bootability. The entire batch was reverted, and the restored profile now boots
and passes the native suite. The old EFI used for recovery was not the repair
reference. The precise individual trigger within the failed batch remains
unproven; no withdrawn refinement is staged or recommended for reapplication.

[EFI-Full-Review.md](EFI-Full-Review.md) records the full section review and its
historical proposals. Detailed logs show MAT support, successful OpenRuntime
rendezvous and APFS acceptance, but those partial successes did not validate the
whole audit profile. Evidence is in
`build/config-full-review-20261023/FAILURE-ANALYSIS.json`,
`RELEASE-CORRECTION.json` and `RESTORED-RUNTIME-PASS.json`.

## Limits

This is bounded functional validation on macOS 15.8.1/24H32 and this single Renoir
machine. It is not a security-hardening or measured peak-performance claim.
Custom SIP/authenticated-root restrictions, SecureBootModel=Disabled, the broad
APFS driver minimums and the CoreMedia workaround are preserved. No serial/UUID
regeneration, new CPU power-management driver, speculative firmware quirk or
internal-disk EFI installation was performed. Longer workloads, other OS builds,
other codec profiles and a second GPU are outside the current hardware evidence.
The earlier intermittent Wi-Fi issue is not declared permanently cured from one
successful cycle. No source changes were pushed.
