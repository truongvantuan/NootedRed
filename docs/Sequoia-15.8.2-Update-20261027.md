# Sequoia 15.8.2 update preparation

Prepared 27 October 2026 for this HP EliteDesk/Renoir machine. This is an in-place
15.8.1 (24H32) → 15.8.2 (24H232) update, not a Tahoe upgrade.
No OS installation, root patch, EFI replacement or reboot is performed by the preparation tools.

## Download verified

Apple InstallAssistant.pkg is at:
`/Users/tvtuan/Downloads/macOS-15.8.2-24H232/InstallAssistant.pkg`.

- Exact size: 15,664,531,445 bytes.
- `pkgutil --check-signature`: signed Apple Software, chain ending at Apple Root CA.
- Package identifier: `com.apple.pkg.InstallAssistant.macOSSequoia`.
- Package revision: `24.7.232` (installer package revision, not Darwin version).
- SHA-256: `aca683767f1d22205a19c8efaa2d11c97227f2203763d47d0237e3b1c4d5c193`.

Record: `build/update-sequoia-15.8.2-20261027/INSTALLER-VALIDATION.json`.
A genuine complete installer does not establish NootedRed compatibility on the new OS.

## Backups and remaining gates

Local backup:
`/Users/tvtuan/Update-Backups/Sequoia-15.8.1-before-15.8.2-20261027-144228`.

The verified backup contains all 123 production EFI files, Git history bundle,
433 tracked/untracked source files, working-tree diff, system settings, wireless
root-patch metadata and the OCLP installer. An APFS local snapshot was created
at `2026-10-27-144836`. The update helper scripts and this runbook are also copied
into the backup's update-kit directory.

This backup is on the system disk and excludes personal data and most ignored
build output. It is not a full independent backup. The user deferred arranging
that backup. Local snapshots are purgeable and are not an assured OS downgrade.

Before installation:

1. Complete and verify a full backup on another disk or network destination.
2. Put the prepared working EFI on a recovery USB and verify it boots. The
   directory `build/update-sequoia-15.8.2-20261027/recovery-media-ready/EFI` is
   prepared; no physical recovery USB has been created or tested by this task.
3. Review 24H232 graphics/media binaries against our build-specific NootedRed
   patches. Family matching alone does not validate GL, Metal or VCN.
4. Have the saved OCLP installer available offline and an alternative internet
   connection if DW1560 wireless root patches need reinstalling.

## Installation strategy after the gates pass

Use either System Settings → Software Update → Sequoia 15.8.2, or the downloaded
full installer. System Settings is supported for a minor update; the standalone
download is an offline inspection/recovery option, not a requirement to change
update method. Do not select macOS Tahoe.

Opening InstallAssistant.pkg installs the installer application into Applications;
it is separate from starting the OS upgrade. Launching the resulting installer
and proceeding through its OS installation is a later user action.

Retain the custom AMD OpenCore configuration, kernel patches, USB map, working
VirtualSMC startup-race build and audio layout 11. Do not use OCLP's **Build and
Install OpenCore** on this machine: our AMD bootloader configuration is maintained
separately. Do not change BIOS, PAT, SIP or SecureBootModel during the OS update.

The OS update can replace the DW1560 system root patches. After installation,
review OCLP's proposed root patches and restore the required Modern Wireless set
only, then reboot. Review a missing privileged helper before patching; the
saved signed OCLP package can restore its installed components if needed.
Do not run `--gui_patch` merely to inspect: it starts patching.

OCLP documentation for minor updates and reapplying root patches:
https://dortania.github.io/OpenCore-Legacy-Patcher/UPDATE.html#minor-updates
The bootloader rebuild guidance there targets its supported Macs; it is not the
bootloader procedure for this custom AMD EFI.

## Verification after returning to macOS

Run:

```bash
bash /Users/tvtuan/Github/NootedRed/build/update-sequoia-15.8.2-20261027/collect-after-update.sh
```

This captures evidence without modifying EFI, launching GPU workloads, applying
patches or requesting sleep. It intentionally does not report all features passed.
Review OS/build, loaded NootedRed/VirtualSMC identities, root-patch state, PCI/USB,
audio, Wi-Fi, Bluetooth, watchdog and current-boot crash evidence. Compare the
mounted EFI against the recorded production manifest when available.

Next validate exact GL/Metal and VDA patch bytes for the new binaries, then run
functional tests individually with capture and stop on a failure or GPU reset.
Do not infer functional hardware decoding from IORegistry properties alone.
Check ordinary menus, PC speaker, USB ports, Wi-Fi and Bluetooth physically.
A system sleep/wake test needs fresh user readiness; previous permission was
explicitly deferred. Verify OS sleep events and automatic Wi-Fi reconnect.
Finally test the original Zalo/App Store workload under capture when ready;
the intermittent HEVC startup hang remains unresolved.

## Recovery limits

EFI restoration repairs an altered bootloader, not an incompatible OS upgrade.
The saved production EFI is a known 15.8.1 baseline; it is not a guarantee that
24H232 will boot. Restore only after identifying the actual ESP, preserving the
failed EFI and comparing the intended files. Do not overwrite an arbitrary disk.

`optional-media-off-diagnostic-config.plist` is validated syntactically but is
not deployed or boot-tested. It turns GLFix off and omits VDA flags for diagnosis;
it is not a permanent fix or proof of 24H232 compatibility.

If the OS itself cannot boot reliably, use independently tested recovery media
and a full backup to recover/reinstall. A local snapshot or EFI folder alone
must not be presented as a complete 15.8.1 downgrade path.
