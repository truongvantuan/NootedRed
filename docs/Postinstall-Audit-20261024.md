# OpenCore and macOS post-install audit, 24 October 2026

A later [allocation/security investigation](Allocation-Security-20261024.md) found recurring allocation bursts and staged a guarded diagnostic RELEASE for the next boot. The 111-file profile described below remains the verified production checkpoint; the staged diagnostic has not yet been runtime-verified.

The isolated ACPI repair has now booted successfully in session
`2B71EF53-4381-447A-A034-E283EB2EFD94`. GPE0MUX is loaded, the duplicate and
missing-name errors are absent, all seven native graphics/compute/GL/media cases
pass before and after a real system sleep/wake. The user confirms normal desktop,
USB, speaker and automatic Wi-Fi rejoin after wake. No GPU reset/hang/new report
was observed. The verified 111-file RELEASE profile is checkpointed for routine
use on this machine/OS. This is bounded functional validation, not a claim that
every OS message is fixed or that security hardening/peak performance is certified.
Final evidence: `RUNTIME-PASS.json` and `FINAL-VERIFIED-EFI-manifest.json`.

## Verified profile and rollback baseline

The audit baseline is boot session `1D6218CF-7591-45B2-976A-0D03961E980B`, macOS
15.8.1/24H32, Darwin 24.6.0. All 110 files initially matched the tested RELEASE
manifest. OpenCore reports `REL-109-2026-10-21`. Our NootedRed RELEASE is UUID
`4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B`. Its three GL pages, Metal LegacyBlend and
SubmitGuard pages, all nine VA pages and NotificationCenter's 904 signed code
pages validate. No GPU workload was submitted by this baseline collection; the
previous seven-case native, browser and real sleep/wake results remain separate
functional evidence in [Validated-Release-20261023.md](Validated-Release-20261023.md).

The ACPI change adds only two table-specific `_L00` method renames and
`SSDT-GPE0-MUX.aml`. Every other config value and executable remains unchanged.
All 111 resulting file hashes were verified using uncached USB reads, and the
matching OpenCore 1.0.9 validator passes. The isolated change passed boot,
the seven-case native suite, a recorded 54-second system sleep/wake and the same
seven cases after wake. RELEASE bootloader and kext binaries were retained.

The verified current config SHA256 is
`0b0a2f8867851b4a0c9d7db8a503cf4d55f8c890327404a8286f4ed6fd177a51`.
Current verified EFI checkpoint:

`/Users/tvtuan/EFI-Backups/OPENCORE-verified-GPE-release-20261024-110003/EFI`

Backup of the exact tested EFI immediately before this change:

`/Users/tvtuan/EFI-Backups/OPENCORE-before-GPE-only-20261024-102219/EFI`

No comparison with the old recovery EFI was used to construct the candidate.
The current native hardware report is `/Users/tvtuan/Downloads/SysReport`.

## Log findings and their implications

| Finding | Evidence and action |
| --- | --- |
| Firmware namespace error repaired | The pre-repair audit boot reports `AE_ALREADY_EXISTS` for `\_GPE._L00` while loading the 14858-byte Artic SSDT. Both native DSDT and that SSDT define the method; the supplied tables reproduce the conflict offline. The current boot has no target duplicate/missing-name error. |
| Isolated GPE repair verified within tested scope | Keep each original method body, rename its definition to XH00/XG00 using signature, OEM table ID and exact length, then dispatch both from one serialized `_L00`. Baseline loads 15 tables with the duplicate; the corrected namespace loads 16 with both preserved handlers. Real GPE0MUX loading, normal devices, one physical system sleep/wake and seven native cases before and after wake pass. This does not exercise every individual interrupt source. The shared ACPICA teardown warning about four outstanding cache allocations is retained in both offline logs. |
| Residual GPU allocation attempts | The pre-repair boot had 43 lines initially and 1672 later. The new boot has nine during the first suite and 6836 shortly after wake, ending at 10:52:17; zero coincide with the post-wake native capture windows. No allocation events were retained in a subsequent three-minute query. All native output checks pass and the settled system remains about 98% idle. Native allocator origin is identified, but its causal client/outer fallback is untraced. No ongoing performance fault or safe memory-policy change is established. These messages are not claimed cured or suppressed; no VRAM spoof or allocator patch was added. |
| Historical AppleALC failures | Ten retained logs show pre-repair AppleALC injection failure. The repaired executable hash, loaded AppleALC and default Internal Speakers verify now. The user confirms speaker sound before and after this boot's system sleep/wake. |
| Stale recovery-log attribution | The newest retained OpenCore file embeds the previous day's 16:34:34 UTC INIT and predates the running boot. Its ForgedInvariant failure belongs to the old recovery EFI. ForgedInvariant is loaded now. The collector separates retained-file failures from current-boot timing candidates; unavailable current log evidence yields `null`, not a clean result or a current fault. Regression tests cover stale, matching, missing, malformed and future timestamps. |
| Failed audit remains unresolved | The previous combined DEBUG/logging + EC/APFS rollout was fully reversed before this audit. Partial log progress and the FSB lookup warning do not identify the exact trigger. Neither withdrawn refinement was reintroduced. |
| Shutdown diagnostics | All 28 available shutdown-stall reports were decoded. Each records approximately 0.96–1.00 seconds of stack sampling; most explicitly started after two seconds. The latest shows launchd collecting the shutdown sample and application processes waiting. These reports do not measure total shutdown duration or prove a prolonged firmware/GPU shutdown hang. |
| Intel power-management warnings | X86PlatformPlugin cannot read Intel-style ACPI P-state arrays on this AMD machine. SMCProcessorAMD is a sensor plugin, not proof of an AMD power-management driver. No CPUFriend/Intel P-state patch or extra CPU power driver was installed. |
| Service and sandbox messages | Current errors include Biome/history initialization, sandbox access denials, launchd retries and asset/account service errors. Retrying arm64-only speech/camera/Rosetta services cannot be enabled on this x86_64 AMD machine by a GPU boot argument. Distnoted/contactsd retries under a noninteractive user domain are retained for follow-up; they are not attributed to OpenCore without evidence. No broad disabling of system services, sandbox or signing enforcement was performed. |
| Clock adjustment | `timed` records a successful approximately 0.319-second initial correction. This does not prove a large RTC offset or TSC failure. Boot-session UUIDs are used to distinguish boots; wall-clock or FAT timestamps alone are insufficient. |

The log inventory contains 43 distinct OpenCore files. All were indexed and
retained privately. Historical kernel evidence covers the available last-day
query, with per-boot counts recorded separately. Current error/fault records were
also grouped by process and message. Stored messages are not assumed to prove
user-visible malfunction solely from their severity label.

That historical query contains 1,099,590 kernel records over 14 boot sessions,
including two `GPURestartBegin` lines in earlier sessions. The current boot has
none in these captures. The populated current error/fault query contains 27,983
records across OS services; severity counts are not a count of hardware faults.
The 1.14 GB historical stream was compressed locally with decompressed SHA256
verification. The original system log store and USB logs were not removed.

## Configuration and post-install checks

| Area | Assessment and retained settings |
| --- | --- |
| ACPI | Current SysReport DSDT and SSDT selectors match exactly. Existing EC/USB renames and the specific invalid I2C test-table deletion remain. Only the duplicate-GPE repair is new. |
| Booter/runtime | Matching RELEASE OpenCore/OpenRuntime retained. Detailed failed-audit logs established MAT support and runtime rendezvous. Keep the working RebuildAppleMemoryMap/SyncRuntimePermissions combination, EnableWriteUnprotector=false and HP filesystem workaround. No MMIO whitelist, slide or ExitBootServices experiment is supported by this boot's evidence. |
| DeviceProperties | Root 1 paths were checked against native `_UID=1` and live device paths. Keep the functioning Ethernet/NVMe built-in properties and audio layout 11. The report's root-zero strings are not authoritative over live/native evidence. No extra GPU-ID or VRAM spoof. |
| Kernel | Eight physical cores match the AMD core-count patch; one PAT variant applies on Darwin 24.6. The Darwin 25.4 TSC patch is outside this OS range. All enabled references and dependency ordering were checked; unchanged executable hashes preserve the prior successful offline link results. No WhateverGreen conflict or diagnostic VMTrace flag is enabled. |
| Misc/logging | Keep RELEASE bootloader and `Target=0`, AppleDebug=false. No fresh OpenCore file log is expected on this quiet profile. Panic capture and recovery access remain. The newest old file is not evidence of today's boot failure. |
| NVRAM | Tested GL/VDA/GFXOFF flags persist. No `-v`, `debug=0x100`, `-NRedDebug` or `-NRedVMTrace`. Native NVRAM is in use; no destructive reset/write test was needed. Identity and deferred Bluetooth variables were retained. |
| PlatformInfo | Existing iMacPro1,1 identity and Custom SMBIOS pairing retained. No serial/ROM/UUID regeneration. Cosmetic CPU naming does not improve execution speed. |
| UEFI | Existing input/GOP settings and HP UnblockFsConnect retained. ReBAR is disabled in the hardware report and both OpenCore resize controls stay -1. APFS minimum overrides remain the tested -1/-1; the withdrawn 0/0 change was not reapplied. |
| Storage | Solidigm P41 Plus reports SMART Verified, TRIM Yes, PCIe 8.0 GT/s x4 and `apst=Yes`. NVMeFix is loaded. No actual storage I/O error is established by the three startup volume-group lookup `error 2` messages followed by successful mounting. No extra `trimforce`, NVMe ASPM experiment or APFS trim-timeout change. SMART is a limited status check, not a media-surface test or filesystem certification. |
| CPU/memory/performance | Settled post-wake sample: 97.75% CPU idle, zero swap, logd near 0%, NotificationCenter 0.0% CPU with all signed pages valid. Earlier high `log` CPU was induced by historical queries. Global logging reports INFO; no global DEBUG override is observed and no logging preferences were changed. No recorded thermal warning is not a temperature measurement. Engineering-sample clocks/voltage and BIOS power settings were retained. |
| USB/sleep | Three-controller map and XHC1→XHC2 correction retained; XhciPortLimit=false. Current profile records Sleep/DarkWake/UserWake counts of 1/1/1 and a 54-second completed cycle, with normal desktop, usual USB ports, speaker and automatic Wi-Fi rejoin confirmed. Caffeine's intentional display-sleep assertion was retained. One cycle does not certify every external device or GPE source. |
| Network | Wi-Fi en1 is associated, has IPv4/default route and passes an interface-bound internet check before and after wake. User confirms automatic rejoin. Post-wake snapshot includes 18 recent scan-failure lines but zero saved-password lookup failures; those scan diagnostics coexist with working connectivity and are not treated as a permanent autojoin cure. Ethernet driver loading is not a cable/throughput test. |
| Sound | Known-good AppleALC hash, live codec/default speaker enumeration and physical speaker operation before/after wake verified. HDMI/input/headphone endpoints are not physically certified by the speaker test. |
| Security | Gatekeeper assessments are enabled. SIP remains custom 0xA03; authenticated root is disabled, FileVault is off, SecureBootModel disabled and Vault Optional. These are explicit limitations, not hardened production security. Enabling FileVault or sealing/vaulting a changing EFI would require a separate recovery plan and compatibility validation. No security changes were silently made. |
| Backup/recovery/install | Verified EFI checkpoints exist. No Time Machine destination is configured in the current query; EFI backups do not protect user files. Boot still uses the OPENCORE USB. Internal-ESP deployment, physical Recovery boot and backup restoration are not certified by file hashing. No internal EFI was overwritten or automatic boot entry registered. |
| iServices/DRM/continuity | Some account-service logs lack a backing account. Actual Apple ID sign-in/messages require user verification; no account/credential changes were made. The Intel Wi-Fi fork documents no AWDL/AirDrop, WPA3-only or mandatory-PMF support; these are driver limitations, not a reason to alter SMBIOS/PCI paths. Protected DRM playback is distinct from the successful unprotected hardware codec tests. |
| Updates | OpenCore is a matching, verified 1.0.9 development revision, not a claim of an official 1.0.9 stable release. Keep exact package/source records. Do not mass-update firmware/kexts/macOS together; recheck ACPI table selectors after BIOS changes and exact driver/cache patches after OS updates. Bluetooth remains deferred. |

The intent is compatibility supported by measurements, not unmeasured gains
from toggling every quirk. GFXOFF holding is retained because the tested full-VDA
profile depends on that stability policy; lower idle power from removing it has
not been established.

Follow-up static analysis identifies the allocation diagnostic in Apple's native
X5000 `AMDHWMemory::allocateLargeBlocks`, reached through
`AMDAccelVidMemory::allocPhysical`. The diagnostic path returns a failed attempt;
the log alone does not establish the outer caller's eventual result. Separate
VRAM/GART driver counters are now captured by the post-boot collector. Evidence
is under `build/postinstall-audit-20261024/allocation-analysis/`. No allocator
patch, false-success return or log suppression was introduced. The remaining
causal request/outer result is unproven. The transient wake burst, successful
post-wake output and settled resource cost do not support another kernel-policy
change in this audit. Preserve these observations for a separate controlled
investigation if a user-visible problem or sustained resource cost recurs.

Primary references:

- [OpenCore's pinned configuration manual](https://github.com/acidanthera/OpenCorePkg/blob/6d8490d3236ad27d5b39063e0ebb55a79272d7a4/Docs/Configuration.tex)
- [NVMeFix diagnostics and power management](https://github.com/acidanthera/NVMeFix#diagnostics)
- [Wi-Fi fork's Sequoia support and documented limits](https://github.com/laobamac/itlwm#airportitlwm-on-macos-sequoia)
- [Dortania post-install checklist](https://dortania.github.io/OpenCore-Post-Install/)
- [ACPICA source](https://github.com/acpica/acpica)

## Routine capture and rollback

Boot and sleep/wake verification are complete for the observed cycle. This
read-only command remains available for later boots or suspected regressions:

```sh
bash /Users/tvtuan/Github/NootedRed/build/postinstall-audit-20261024/collect-after-boot.sh
```

The result requires a boot-session UUID different from the pre-change baseline, exact profile file hashes, actual
GPE0MUX load evidence and absence of the target ACPI errors. Missing load evidence
does not pass. The seven-case suite has already passed before and after wake;
`--exercise` selects it for a future justified regression check and stops after a
functional failure or GPU fault. No further reboot or workload is required to
finish this audit.

Rollback changes only this test's config and added SSDT, with guards against
overwriting unrelated subsequent EFI work:

```sh
python3 /Users/tvtuan/Github/NootedRed/build/postinstall-audit-20261024/stage-gpe.py --rollback
```

The automatic staging transaction was checked and read back; the rollback path
is prepared but has not been exercised through a physical failed boot. Both the
pre-change tested checkpoint and the new verified checkpoint are retained. The
current profile has passed the stated runtime scope; broader hardware/OS and
security limits above remain explicit.

Evidence is under `build/postinstall-audit-20261024/`: `baseline-current/`,
`capture-20261024-100957/`, `shutdown-reports/`, `CURRENT-OPENCORE-ATTRIBUTION.json`,
`gpe-only-candidate/PREPARATION.json`, `GPE-DEPLOYMENT.json`, `RUNTIME-PASS.json`,
`POSTWAKE-ALLOCATION-CORRELATION.json` and the collectors.
Raw logs/config contain private machine data and are retained locally rather
than copied into this report.
