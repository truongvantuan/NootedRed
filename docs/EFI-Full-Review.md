# Full configuration review: HP 872E, OpenCore 1.0.9

24 October: the later [post-install audit](Postinstall-Audit-20261024.md) stages
an independent, single-purpose GPE namespace repair and fixes stale-log attribution
in the collector. It retains the RELEASE binaries; boot, seven native cases before
and after real system sleep/wake, ordinary devices and Wi-Fi auto-rejoin now pass.
The withdrawn DEBUG/EC/APFS batch described below remains withdrawn.

**Audit deployment withdrawn after a reported boot hang.** The user waited more
than five minutes at the startup screen and used a separate old EFI for recovery.
That old EFI is not the repair reference. The complete audit batch has now been
reversed on OPENCORE: matching OpenCore RELEASE files and the exact recorded
pre-audit tested config are restored, while the current NootedRed RELEASE and
repaired AppleALC are preserved. All recorded boot-input hashes match the tested
RELEASE profile. Boot after restoration is now confirmed: the expected RELEASE
identities, all patch bytes and all seven native cases pass, and the user confirms
normal desktop/menus, PC speaker and Wi-Fi. See
[Validated-Release-20261023.md](Validated-Release-20261023.md).

The mistake was introducing the DEBUG/logging switch and two config refinements
together, without a successful boot comparison. Static validation did not prove
bootability. The precise individual cause is unproven. The photo's FSB lookup
message is DEBUG_INFO and other captured runs calculate frequency successfully;
Watchdog status 0 means the configured watchdog is disabled, not an error code.
The following review records the withdrawn candidate, not current applied tweaks.
Failed EFI/logs and the restoration hashes are preserved under
`build/config-full-review-20261023/`; see `RELEASE-CORRECTION.json`.

The tested NootedRed RELEASE build passes seven native cases before and after a
recorded system sleep/wake, plus browser WebGL/video/fullscreen. The user confirms
normal desktop, menus, PC-speaker playback and automatic Wi-Fi reconnection after
that cycle. Evidence is in `build/production-release-20261023/RUNTIME-PASS.json`.
Bluetooth remains deferred by request.

The following review extends that functional verification to every top-level
section of `config.plist`. It records the subsequently withdrawn proposals and
the evidence learned from their failed audit boot. No refinement is still staged.

## Firmware report and live-device cross-check

Source: `/Users/tvtuan/Downloads/SysReport/Report.json` and its native ACPI tables.
Board 872E, BIOS S27 02.23.00, Renoir 1002:1636, Realtek ALC897 on 1022:15E3,
Intel 8265, Realtek 8168, AMD 500-series SATA and Solidigm P41 Plus NVMe match the
running hardware. The report's CPU codename label is inconsistent with its GPU
PCI identity; this deployment follows the detected device IDs and compatibility
profile rather than treating that label as an independent hardware identification.

The report writes PCI paths with `PciRoot(0x0)`, but native DSDT PCI0 has `_UID=1`
and live gfxutil returns `PciRoot(0x1)`. The existing Ethernet, NVMe and audio
property paths match live gfxutil. Do not replace them blindly with the report's
root-zero strings. Ethernet/NVMe built-in flags are present.

Audio layout 11 is retained in live `alc-layout-id=11`; `layout-id=7` is the
separate value presented to AppleHDA. [AppleALC's implementation](https://raw.githubusercontent.com/acidanthera/AppleALC/master/AppleALC/kern_alc.cpp)
preserves the requested layout and can replace the reported layout. This is not
a reason to change the working audio layout.

## Section review and withdrawn proposals

| Section | Result and action |
| --- | --- |
| ACPI | All four active AML files have valid checksums and decompile. USB reset references XHC2 and agrees with the controller rename. Native DSDT matches both rename patterns once; the narrow table drop matches only ssdt9 (Artic). Scope the formerly unrestricted EC rename to DSDT/OEM 872E/57445 bytes, Count=1. Offline replacement produces identical bytes on this firmware. |
| Booter | Preserve the working memory-map/runtime-permission combination, slide handling and HP firmware workarounds. EnableWriteUnprotector is off. No relocation/MMIO whitelist change is supported by current evidence. A detailed DEBUG log is needed to confirm MAT/memory-map decisions; success under the current settings does not establish that every quirk is necessary. |
| DeviceProperties | Preserve the three verified paths and requested audio layout. No VRAM spoof, extra GPU device-ID injection or generic built-in flags are added. The 512 MiB GL budget issue is corrected in NootedRed, not by inventing more reserved VRAM. |
| Kernel | CPU count is 8 physical /16 logical; the core patch encodes 8. Patch bytes/ranges match the saved AMD reference, with one active PAT variant. Kext file references and dependency order pass; all 15 executable kexts link offline. Existing SATA/NVMe drivers correspond to actual reported hardware. Preserve working compatibility quirks; no speculative CPU power-management or TSC patch is added. |
| Misc | The quiet profile already removes debug output and retains panic capture/recovery access. Picker scan policy permits the current USB/recovery workflow. DmgLoading remains Signed. A temporary audit enables file-only logging; final quiet settings are prepared. No new automatic boot-target registration is made. |
| NVRAM | Preserve the tested full GL/VDA/GFXOFF flags and RestrictEvents CPU/update settings. Native flash writes are enabled; the selected arguments persist across reboots. Keep current SIP settings for this audit, and leave Bluetooth variables untouched. The current SIP/authenticated-root restrictions are reduced; this review does not certify a hardened security configuration. |
| PlatformInfo | Preserve iMacPro1,1 and existing identity. Custom SMBIOS mode is paired with CustomSMBIOSGuid. Do not regenerate serial/UUID/ROM or change SMBIOS after the functioning audio/USB/graphics tests. Cosmetic CPU naming is not a performance control. |
| UEFI | Keep matching OpenRuntime, HP filesystem-connect workaround, input/GOP settings, FirmwareVolume override and recovery driver. Both BAR-resize settings remain disabled, matching the report's disabled ReBAR. Set APFS MinDate/MinVersion from -1/-1 to 0/0: the installed APFS is 2332.140.13 and exceeds the documented default minimum. |

OpenCore's pinned 1.0.9 manual and source are under
`build/efi-audit/OpenCorePkg/` at commit
`6d8490d3236ad27d5b39063e0ebb55a79272d7a4`. The public
[configuration reference](https://raw.githubusercontent.com/acidanthera/OpenCorePkg/master/Docs/Configuration.tex)
documents these options. These decisions target the current firmware/OS; recheck
the table-dependent patches after a BIOS update. No unmeasured performance gain
is claimed from changing options for their names alone.

## Retained log findings and fresh capture

The newest retained log, `opencore-2026-10-23-153600.txt`, embeds boot.efi INIT
15:36:06 UTC and belongs to the preceding approximately 22:36 local boot. It is
not the current 22:44 RELEASE boot. Its missing-variable/file lookups continue
through EXITBS into the successfully booted OS; they are not evidence by
themselves that a boot failure needs a quirk change. It lacks detailed OCABC
information. The installed RELEASE build compiles warning/error output, while
the matching DEBUG build includes INFO output.

Both downloaded 1.0.9 package hashes match the
[build-repo release record](https://github.com/dortania/build-repo/releases/tag/OpenCorePkg-6d8490d).
All four installed OpenCore boot files match that exact RELEASE reference.
The audit switches those four files to the matching DEBUG package and enables
file-only logging (`Target=65`, `AppleDebug=true`). **NootedRed remains RELEASE**,
UUID `4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B`.

Before staging, the complete EFI backup was verified at:
`/Users/tvtuan/EFI-Backups/OPENCORE-before-config-full-audit-20261023-230847/EFI`.
Exactly four OpenCore files and config.plist changed. Both the audit and final
quiet configs pass the matching 1.0.9 validator. Guarded restore inputs pass.

The retained command now checks the restored quiet RELEASE profile:

```sh
bash /Users/tvtuan/Github/NootedRed/build/config-full-review-20261023/collect-after-boot.sh
```

The read-only collector requires the NootedRed RELEASE identity/actual patch
bytes and checks the recorded tested file hashes and RELEASE bootloader. The
retained DEBUG logs have been examined: MAT support and OpenRuntime rendezvous
succeed, APFS is accepted, and both ACPI replacements apply once. Those partial
results did not prove full-boot stability, and neither refinement was retained.
`restore-opencore.py --check` now verifies the restored files without writing.
Its old restore/refinement actions are disabled because the audit was withdrawn.

Evidence and per-file hashes: `build/config-full-review-20261023/DEPLOYMENT.json`,
`SECTION-AUDIT.json`, `SysReport-ACPI-headers.json` and `OpenCore-reference-check.json`.
