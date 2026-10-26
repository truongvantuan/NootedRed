# Device-specific EFI review, 24 October 2026

All eight configuration sections have been reviewed against the current HP
hardware report, live device identities, matching OpenCore 1.0.9 source and the
AMD patch reference. The current map accounts for the user's five USB-A ports,
one USB-C port and internal Bluetooth. The production refinement is **staged for
the next boot**, not yet runtime-verified. The current OS still runs diagnostic
NootedRed RELEASE UUID `8E3E2229-FE15-3AC6-ACBC-FFD54C1F96E5` until reboot.

Only two EFI files changed: `OC/config.plist` and the NootedRed executable.
The target restores tested production RELEASE UUID
`4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B`, removes `-NRedAllocTrace`, and corrects
one **inactive** boot-audio device path. Existing functional config values are
identical to the tested production checkpoint; boot audio stays disabled. No
additional firmware quirk, kernel patch, identity or USB-map change was justified.

## Hardware facts and selection rules

Native report: `/Users/tvtuan/Downloads/SysReport`, Report.json SHA256
`1953a1afaf55d5f2640e5da7fc01d69b8926b7fb0834eef4a298f708107254bf`.
Board 872E, S27 BIOS 02.23.00, UEFI, 32 GiB RAM. Native DSDT is 57445 bytes,
SHA256 `67661c36dc20bd02920cd640dede74f819e9f0e54fad4af3db63e8dd5d6c68f6`.
No later firmware release is established by this audit and no firmware is flashed.

Live CPU is AuthenticAMD family 23/model 96/stepping 1 with eight physical cores
and sixteen threads. That identifies the Renoir profile; the report's separate
“Picasso” label is inconsistent with live CPUID and GPU 1002:1636. Do not select
patches or power settings from that label. The reserved iGPU memory remains the
actual BIOS maximum 512 MiB; a large GART address space is not additional VRAM.

Native PCI0 `_UID=1` and live gfxutil confirm root 1, despite root-zero path
strings in the report. All three injected paths match real devices:

| Injection | Verified path and purpose |
| --- | --- |
| Realtek 10EC:8168 Ethernet | Root 1 → 2,1 → 0,2 → 9,0 → 0,1; built-in flag retained. |
| Solidigm 025E:F1AB NVMe | Root 1 → 2,2 → 0,0; built-in flag retained. |
| AMD 1022:15E3 HDEF / ALC897 | Root 1 → 8,1 → 0,6; requested AppleALC layout 11 retained. |

The macOS audio injection was already correct. The corrected field is the
separate `UEFI/Audio/AudioDevice`, formerly an inactive Intel root-0/1b,0 default.
It now points to the real HDEF controller, with `AudioSupport=false` and no
AudioDxe driver. This does not add a startup chime or alter working PC-speaker
routing. Layout 11 is the requested AppleALC layout; an AppleHDA-reported layout
7 does not by itself establish an injection error.

## Section decisions

| Section | Device-specific assessment and action |
| --- | --- |
| ACPI | Five added AML tables have valid lengths/checksums. Native EC and XHC rename patterns each match exactly once in DSDT. The two GPE definitions match their exact DSDT/ssdt7 selectors; the dispatch SSDT is retained. The exact Artic/5132-byte drop matches only ssdt9. The broad EC selector currently has exactly one match; the withdrawn EC-scoping trial was not reintroduced. Recheck table-dependent settings after any BIOS update. |
| Booter | Retain the tested MAT-supported memory-map/runtime-permission combination: RebuildAppleMemoryMap and SyncRuntimePermissions on, EnableWriteUnprotector off. Retained detailed history confirms MAT and OpenRuntime rendezvous. Preserve working SetupVirtualMap and slide handling on this OEM firmware; generic chipset guidance alone is not a reason to flip them. No MMIO whitelist, BAR, forced EXITBS, relocation or new memory reservation. Individual workaround necessity is not claimed isolated. |
| DeviceProperties | All three root-1 paths agree with live devices. Keep Ethernet/NVMe built-in and audio layout 11. No device-ID, VRAM or cosmetic GPU spoof. |
| Kernel | All 15 patch definitions applicable to Darwin 24.6 match current AMD upstream semantics after normalizing only the physical-core immediate 8. Exactly one Sequoia PAT variant applies. The 27 stored entries include older/future ranges and exclusive alternatives; they are not 27 simultaneous patches. Darwin 25-only additions do not affect this OS. ProvideCurrentCpuInfo and AMD DummyPowerManagement remain; Intel PM/CFG-lock fixes stay off. Keep HP LAPIC/RTC workarounds and Lilu symbol retention. |
| Kernel extensions | All 15 configured executables are loaded; configured dependencies precede their consumers. The two additional enabled entries are codeless personalities. USBToolBox/UTBDefault remain disabled while USBMap is active. Matching source/installed paths are valid. The production NootedRed executable is restored from the verified 111-file checkpoint, with the same bundle metadata. Sensor plugins are attached; SMCProcessorAMD is a temperature/power-monitoring plugin, not proof of native CPU power management. |
| Misc | RELEASE OpenCore, Target=0, AppleDebug=false, panic capture and built-in picker retained. Auxiliary recovery/NVRAM-reset access remains. No DEBUG bootloader switch, new launch registration, cosmetic booter patch or speculative boot delay. Security/recovery tradeoffs are separate from firmware correctness. |
| NVRAM | Restore production arguments: `keepsyms=1 -NRedGLFix -NRedVCNNoGfxOff -NRedVDA`. Remove only allocation tracing. Native flash writes and explicit per-variable overrides retained. Deferred Bluetooth variables remain untouched. No NVRAM reset. |
| PlatformInfo | Keep working iMacPro1,1 identity and Custom SMBIOS mode paired with CustomSMBIOSGuid. Serial/MLB/ROM/UUID formats checked privately, without regenerating identifiers or making external serial queries. Cosmetic processor reporting is not a performance setting. |
| UEFI | Matching RELEASE OpenCore/OpenRuntime/ResetNvramEntry and HfsPlus references are valid. Keep HP filesystem-connect workaround, USB ownership handoff, GOP/input settings and FirmwareVolume override. ReBAR is reported disabled and both resize controls remain -1. Intel VMX is not AMD SVM; no EnableVmx change. Correct only the inactive boot-audio path. |

Every stored scalar and empty container has an explicit decision in
`build/device-config-audit-20261024/CONFIG-DECISIONS.json`: **901 records**.
This includes duplicate per-entry fields and inactive defaults; it does not mean
901 independent hardware functions were exercised. Static, current-runtime and
new-boot evidence are kept separate.

## USB topology

| Controller | PCI match | Configured logical ports | Physical role |
| --- | --- | --- | --- |
| PT00 | `1:0:0` | 5 | One USB-C pair, one USB-A pair, internal Bluetooth marked 255. |
| XHC0 | `6:0:3` | 4 | Two USB-A high/super-speed pairs. |
| XHC2 | `6:0:4` | 4 | Two USB-A high/super-speed pairs. |

All three live controller maps exactly match the configured merge properties.
Port IDs are unique per controller and each map is below fifteen logical ports.
`port-count` is the highest numbered port, not the number of selected entries.
The XHC1→XHC2 rename agrees with both USB reset AML and the matching personality.
XhciPortLimit remains false. User confirmation: “5 A, 1 C, 1 internal bluetooth.”

Previously used-port and sleep/wake operation were confirmed. This audit did not
physically test USB2 and USB3 speed on every connector or both USB-C orientations;
those are functional coverage limits, not a basis for inventing extra mapped ports.

## Timekeeping, logs and limits

ForgedInvariant 1.5.0 is loaded and attached. The referenced source handles
runtime/wake synchronization for AMD family 17h and exposes an optional periodic
mode. No evidence here proves that enabling periodic synchronization, installing
a second TSC driver or setting an experimental UEFI TscSyncTimeout would fix the
observed `sudo` future-timestamp rejection. The UEFI timeout cannot replace a
runtime sleep/wake synchronizer. Retain TscSyncTimeout=0. A five-sample passive
current-boot clock check observed no backward step; that short awake check does
not verify clock behavior across sleep. A passive cross-wake recorder is prepared.

An upstream timestamp-rollback report concerns a different AMD laptop on Darwin
25 with a different Ethernet driver. It is a reason to measure, not proof of the
same cause on this HP/Darwin 24 machine. No driver was removed based on that report.

OpenCore file history was inspected. Detailed retained logs show MAT support and
runtime rendezvous; those records are historical, including a withdrawn failed
batch, not proof they belong to the current boot. Current Target=0 intentionally
produces no new file log. The early Apple Platform Info FSB lookup failure later
falls back to an approximately 99.8 MHz result in retained logs; it is not itself
a reason to change CPU frequency/slide settings. Current matching binary hashes
and actual macOS boot evidence remain separate checks.

Known limits stay explicit:

- GPU allocation warnings are substantial and unresolved. No OpenCore setting
  change in this review is claimed to fix or hide them.
- SIP remains 0xA03, authenticated-root enforcement disabled, FileVault off,
  SecureBootModel Disabled and Vault Optional. Signed recovery loading remains.
  The full-SIP-only candidate is separate and uninstalled. Broad APFS minimums
  remain -1/-1; the withdrawn APFS adjustment is not bundled back in.
- A working sensor plugin does not establish peak CPU power efficiency. No
  speculative power-management driver, CPUFriend, overclock or thermal change.
- Intel 8265/AirportItlwm feature limits and current `kern.hv_support=0` remain
  platform/driver limits; changing unrelated EFI switches does not establish support.
- Bluetooth troubleshooting remains deferred by the user's request.

## Internal system-disk installation

The user copied the prepared EFI onto the system disk. All 111 internal files
match the production manifest, with no missing, changed or extra files. The
selected ESP is currently disk0s1, mounted at `/Volumes/EFI`, partition UUID
`9EB4E64C-8023-4757-8627-D51981F51B54` on the internal Solidigm NVMe. The verifier
resolves that stable UUID instead of assuming a USB volume name or disk number.
The agent did not write the internal EFI. A readback-verified checkpoint of the
user-installed copy is recorded in `INTERNAL-TARGET.json`; it is not a backup of
whatever internal EFI existed before the user's copy.

For the first provenance test, disconnect the OPENCORE USB and select the internal
OpenCore entry in the HP boot menu. Matching files alone do not prove the running
bootloader's source. After a successful internal boot, verify that ordinary default
startup also selects it before calling the installation persistent. Current
LauncherOption remains Disabled; copying files alone does not prove a firmware
boot entry/default has been registered. No firmware boot-order change was made by
the agent. Keep the tested USB available for recovery.

## Deployment and completion gates

Full preceding diagnostic checkpoint:

`/Users/tvtuan/EFI-Backups/OPENCORE-before-device-refinement-20261024-161541/EFI`

Production source checkpoint:

`/Users/tvtuan/EFI-Backups/OPENCORE-before-allocation-trace-20261024-143609/EFI`

The latter is the recently tested 111-file profile, not the old recovery EFI.
Target config SHA256:
`c5fc3862840d876675b52e63601622f36484105bdd59b8eaed064d45df37dda7`.
NootedRed target SHA256:
`0d0d56e05284cfa6b73b712f7f60763f4f1358568d5b88eae2c1ccb3ae13a85e`.
Matching 1.0.9 ocvalidate passes; every staged file passed uncached USB readback.
The preflight correctly rejects collection on the still-running diagnostic boot.
No reboot has been initiated by the agent for this deployment.

After booting the internal OpenCore copy with the USB disconnected, mount its EFI partition and collect the guarded native suite:

```sh
bash /Users/tvtuan/Github/NootedRed/build/device-config-audit-20261024/collect-after-boot.sh --exercise
```

It requires a new boot session, exact staged hashes, production UUID, absent
allocation instrumentation, expected graphics/media bytes, all executable kexts,
matching live USB maps, GPE0MUX load and no observed target ACPI/GPU fault. Native
output cases stop after a failure/reset; code-page installation alone is not a
rendering test. Physical device operation and a real system sleep/wake still need
confirmation on this final profile. Later passive captures omit `--exercise`.

The following guarded rollback targets only the original **USB staging**. It is
not an internal-disk restore command. It restores this deployment's config and
executable only if the original USB hashes still match:

```sh
python3 /Users/tvtuan/Github/NootedRed/build/device-config-audit-20261024/stage-profile.py --rollback
```

The overall audit remains **pending final boot/runtime validation**.
`COMPLETION-AUDIT.json` records the requirements and missing evidence. No universal
“best performance” or production-readiness certification is inferred from static
validation alone.

Primary references:

- [Matching OpenCore source manual](https://github.com/acidanthera/OpenCorePkg/blob/6d8490d3236ad27d5b39063e0ebb55a79272d7a4/Docs/Configuration.tex)
- [AMD Vanilla instructions](https://github.com/AMD-OSX/AMD_Vanilla/blob/eaf52ef292abf4ebec899df6d48626569ba50cc6/README.md)
- [AMD Vanilla patch reference](https://github.com/AMD-OSX/AMD_Vanilla/blob/eaf52ef292abf4ebec899df6d48626569ba50cc6/patches.plist)
- [ForgedInvariant source](https://github.com/ChefKissInc/ForgedInvariant/blob/136a5f74e189963a10b3abb9dda5c57cbb0041c7/ForgedInvariant/TSCSyncer.cpp)
- [Different-machine timestamp report](https://github.com/ChefKissInc/ForgedInvariant/issues/20)
- [SMCProcessorAMD's documented purpose](https://github.com/macos86/SMCProcessorAMD)

## First automatic internal-disk boot

On 24 October at 16:44:48 local time, boot session
`43326916-09B7-427B-9DB6-B35098B9ADF9` loaded production RELEASE
NootedRed `4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B` with the expected
production arguments and no allocation trace. The user confirmed the USB was
unplugged before startup and internal OpenCore started automatically. The live
disk inventory contains only the internal physical disk and APFS container.
All 111 internal EFI files match the staged manifest. Native output tests and
final-profile physical sleep/device confirmation are still in progress.

A non-writing FAT check reported the volume dirty and FSInfo free-space count
off by one cluster (324882 recorded, 324881 counted), with no directory or
orphan-cluster errors reported. Disk Arbitration read-only mount failed; direct
`mount_msdos -o rdonly` succeeded. No filesystem repair was performed.
See `INTERNAL-BOOT-CONFIRMATION.json` and `boot-20261024-165012-1514`.

The internal production boot subsequently passed all seven native output cases:
Metal render/compute, H.264 and HEVC decode/encode, and OpenGL render. All 15
executable kexts and the three live USB maps match. GPE0MUX loaded with no
observed duplicate/missing-name errors; no GPU reset/hang was observed. The user
confirmed normal desktop/menus, usual USB ports, PC speaker and Wi-Fi.
Allocation warnings remain unresolved: 74,611 records were observed in this
boot's query despite successful functional cases. Final-profile sleep/wake
remains pending: the user explicitly asked to wait before requesting sleep.
