# Production logging profile — 27 October 2026

At the user's request, removed temporary diagnostic settings from the working
internal EFI after DW1560 connection and real system sleep/wake verification.
This is a production logging configuration, not proof that every feature or
all long-term stability scenarios have been tested.

## Applied configuration

Boot arguments:

```
-NRedGLFix -NRedVCNNoGfxOff -NRedVDA
```

Removed keepsyms=1, -v, debug=0x100, -NRedVCNTrace and -NRedVMTrace. The local
source checks require the two trace flags before installing their diagnostic
routes. The currently running kernel retains its prior flags until reboot.

Misc/Debug: AppleDebug=false, ApplePanic=false, Target=0, DisplayLevel=0,
DisplayDelay=0, SysReport=false. Tested DisableWatchDog=true and the valid
default LogModules selector are unchanged. This disables OpenCore file/console
logging and OpenCore panic export; normal macOS diagnostic reporting remains.
NVRAM/Delete already includes boot-args so the new value replaces the prior
one on the next boot; no NVRAM reset was performed.

OpenCore.efi, BOOTx64.efi, OpenRuntime.efi and ResetNvramEntry.efi exactly match
the existing 1.0.9 RELEASE reference. NootedRed matches the recorded local
RELEASE build identity; opt-in tracing is disabled by removing its boot args.
The patched VirtualSMC RELEASE and all other kext bytes were retained. No
functional fixes were replaced with upstream binaries. DW1560 legacy drivers,
root patches, SIP/AMFI compatibility settings, USBMap, audio layout, AMD kernel
patches and boot picker are unchanged. The Sonos 500 ms preference is unchanged.

Four OpenCore logs were copied with verified hashes to the backup and removed
from the EFI volume. Before/after manifest verification confirms config.plist
was the only changed file inside EFI; remaining enabled kext paths and
OpenCore 1.0.9 configuration validation pass.

Backup: /Users/tvtuan/EFI-Backups/INTERNAL-before-production-logging-cleanup-20261027-140626
Evidence: build/production-logging-cleanup-20261027/DEPLOYMENT.json.

## Next boot

Reboot manually when convenient, then run this read-only verification:

```sh
python3 /Users/tvtuan/Github/NootedRed/build/production-logging-cleanup-20261027/verify-after-boot.py
```

It checks the active boot arguments and absence of enabled VM/VCN diagnostic
trace markers. Confirm desktop/menus, USB, speaker, Wi-Fi and Bluetooth after
boot. No reboot was initiated during this deployment. To roll back this
configuration, restore only OC/config.plist from the named backup after checking
the correct internal EFI. Do not restore an unrelated old full EFI.

Reference for disabling OpenCore file logging:
https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/debug.html#disabling-all-logging

## Bootstrap / LauncherOption review

The mikigal Bootstrap section recommends LauncherOption=Full after moving EFI
to the internal disk. The installed OpenCore manual defines Full as creating or
updating a top-priority firmware boot option. LauncherPath=Default targets
OpenCore.efi directly. RequestBootVarRouting is required for Full and is already
true, with OpenRuntime enabled. Current LauncherOption remains Disabled.
Both EFI/OC/OpenCore.efi and the fallback EFI/BOOT/BOOTx64.efi are present.
The user previously confirmed automatic internal boot with USB unplugged.

Direct registration reduces dependence on the fallback BOOTx64.efi path when
other OS installers/updaters replace that file. It does not prevent deletion or
overwriting of OpenCore/config/kext files and is not Secure Boot or an EFI
backup mechanism. It provides no GPU/network/sleep performance gain.
Full also updates boot priority at startup and depends on firmware NVRAM boot
entry compatibility, which is not established merely by file checks. The
current macOS NVRAM query does not expose BootOrder/BootCurrent, and bless
--getBoot could not access efi-boot-device. That does not prove firmware boot
entries are absent. Exact current firmware selection remains unverified.

For the currently working internal boot this is optional. Verify the pending
production-logging reboot first. If later adopted, change only LauncherOption
to Full, keep LauncherPath Default and RequestBootVarRouting true, use the
internal disk only and confirm the persistent entry/default boot after reboot.
An existing fallback loader and recovery EFI should remain available.
No EFI or firmware/NVRAM setting was changed in this review.

Evidence: build/bootstrap-review-20261027/SUMMARY.json.
Sources:
- https://github.com/mikigal/ryzen-hackintosh/blob/master/README.MD#bootstrap
- https://github.com/acidanthera/OpenCorePkg/blob/6d8490d3236ad27d5b39063e0ebb55a79272d7a4/Docs/Configuration.tex
