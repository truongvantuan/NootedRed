# DW1560 shutdown/restart failure — 2026-10-27

The user reports Bluetooth fails after power-off and Restart also fails.
The failing capture is boot DD9B22D6-D814-4111-8817-E24F4BD89891. USB device
0a5c:216f remains present on the same internal port, with BrcmPatchRAM3 matched
to firmware key BCM20702A1_001.002.014.1443.1572_v5668. BlueToolFixup 2.7.3,
BrcmFirmwareData 2.7.2 and BrcmPatchRAM3 2.7.2 are loaded. System Profiler shows
no controller address, firmware v0 c0, controller off and UART transport.

The decisive current log pattern is repeated failure to open /dev/cu.BLTH,
followed by failed POSIX driver/H4BC transport initialization and bluetoothd
restart reason 1201. There are 40 UART/H4BC failure records in the collected
five-minute error window. This is before paired-device reconnection.

The system reports iMacPro1,1 / Mac-7BA5B2D9E42DDD94. This board is not in
BlueToolFixup's USB-board list. Upstream disabled automatic board-ID patching
on macOS 14+, but provides -btlfxboardid to enable it when required. Its
validation-page callback replaces the first USB-board ID string in BlueTool
and bluetoothd with the actual board identifier. The installed BlueToolFixup
binary contains the option and reference string; the current bluetoothd binary
also contains the reference USB-board string. This fits the observed USB
hardware versus UART selection mismatch. It is a supported candidate fix,
not a completed hardware diagnosis or verified repair.

No assumption was made that USB bcdDevice proves firmware upload failure:
the earlier working capture has the same descriptor value 274. The Broadcom
NVRAM Add/Delete entries are already configured; their absence at runtime
alone is not proof of missing boot configuration. No firmware delay or address
bypass option was added without evidence for those different failures.

## Staged change

Backed up and hash-verified the complete internal EFI to:
`/Users/tvtuan/EFI-Backups/INTERNAL-before-Bluetooth-boardid-20261027-234405`.

Added only `-btlfxboardid` to the existing boot-args string. Existing
boot-args deletion/reinjection is configured, so no NVRAM reset was requested.
Candidate config passes OpenCore 1.0.9 ocvalidate. Full file comparison confirms
only OC/config.plist changed; semantic comparison confirms only this string
changed. All kext bytes, SMBIOS, USB map, Phantom r2, NootedRed and pairings
are unchanged. EFI was flushed and unmounted. No automatic reboot occurred.

Evidence/rollback: `build/bluetooth-power-20261027/DEPLOYMENT.json`, original
config, candidate config, validation output, startup/current transport logs,
USB snapshot and Bluetooth snapshot. Rollback helper restores only the
pre-test config after checking partition identity and expected candidate hash:
`python3 build/bluetooth-power-20261027/restore-config.py` with EFI mounted.
It refuses to overwrite subsequent configuration changes.

## Required verification

Restart manually, test Bluetooth discovery/connection without resetting
pairings, then collect:

```bash
bash /Users/tvtuan/Github/NootedRed/build/bluetooth-power-20261027/collect-after-boot.sh
```

Require active boot argument, controller on with a non-null address, usable
firmware/controller information, and no repeated UART/H4BC initialization loop.
Functional keyboard/phone connection must be confirmed separately. Then test
actual shutdown/power-on to verify the originally reported failure mode.
An earlier warm-session success does not establish power-cycle reliability.
If UART selection persists, verify the live page patch before introducing
firmware timing changes. A complete AC-power reset/control may still be useful
for the separately reported similar Linux behavior; it is not yet performed.

Sources:
- https://github.com/acidanthera/BrcmPatchRAM/blob/master/BrcmPatchRAM/BlueToolFixup.cpp
- https://github.com/acidanthera/BrcmPatchRAM/blob/master/Changelog.md
- https://github.com/acidanthera/BrcmPatchRAM/blob/master/README.md

## Restart verification — 23:49

Boot 89F6DC00-322E-4F74-AD61-BE01B939B6BF has -btlfxboardid active. The
controller now reports USB transport, powered on, a non-null address and
firmware v8718 c5668. The successful log query found zero current-boot
UART/H4BC transport failures in its ten-minute capture window. Phantom r2
and all three Broadcom kext UUIDs remain unchanged. The user confirmed
Bluetooth works normally without resetting/re-pairing, and confirmed this
was Restart. This verifies the restart failure is resolved in this test and
supports the board-ID/transport-selection diagnosis. Actual shutdown/power-on
reliability remains unverified. Evidence: boot-20261027-234853/.

## AC-connected shutdown failure — 28 October

Boot BD604B43-D704-4CDF-8727-4112E6D9F0F7 started at 07:49:26 after overnight
shutdown with AC connected. The board-ID argument is active and transport is
now USB, but the controller is off/address NULL/firmware v0 c0. bluetoothd
repeatedly reports that it cannot find a USB Bluetooth controller after 15
seconds, failing USB transport initialization. The DW1560 itself still
enumerates as 0a5c:216f. Thus yesterday's board-ID change fixed the UART
selection/restart case but did not establish shutdown endurance.

With user approval, temporarily stopped the Logitech G HUB updater, tray and
agent, releasing its USB client, then restarted bluetoothd. Ten observations
over approximately 50 seconds still showed no usable controller. Restored all
three helpers; their new processes were confirmed running. This does not
justify permanently disabling G HUB or prove it can never contribute to a
boot race. No pairing, firmware-delay, USB-map or additional EFI change was
made during the test. Evidence: ghub-test-20261028-082535/.

The user adds two important controls: the symptom also occurs on Linux despite
Wi-Fi detection, and removing AC power restores Bluetooth. BIOS Fast Boot is
confirmed Disabled; S5 Maximum Power Savings is Enabled. Saved SysReport
identifies S27 02.23.00, released 2026-07-24 (snapshot, not live firmware
attestation). HP's commercial BIOS guide describes S5 Maximum Power Savings
as minimizing off-state consumption, not guaranteeing equivalence to AC
removal. ACPI distinguishes S5 soft-off from G3 mechanical-off. Retained
power/card firmware state or incomplete power/reset sequencing is therefore
a stronger hypothesis, not proof of a specific HP BIOS defect. Linux lsusb,
btusb/btbcm logs, rfkill and exact distro/kernel evidence are still required
to distinguish a missing USB function from firmware/HCI initialization failure.
A read-only portable collector is prepared as collect-linux.sh.

NootedRed 1.2.0 was installed at 08:17 but the running kext throughout these
failures/tests was still 1.1.1 UUID 382D20A6-DBBB-3E0E-8282-CDCE0420B1BF.
The newly merged kext cannot explain this pre-install captured failure.
The official same-version BrcmPatchRAM3 DEBUG 2.7.2 is downloaded/hash-verified
and prepared separately, not installed. Its FirmwareLoaded property is not a
success proof: uploader source sets it before the attempted upload.

Next controlled sequence: boot/verify the new NootedRed with BIOS unchanged
(use the known AC-disconnect recovery if needed), then test only S5 Maximum
Power Savings Disabled, keeping Fast Boot Disabled and EFI fixed. Start from
a known healthy controller state, then test normal shutdown/power-on with AC
connected. This tests whether avoiding the current S5 power-gating behavior
changes the failure; it is not a promised repair. Record the result and revert
the test setting if it offers no benefit. No BIOS flash or reset is performed.

Sources added:
- https://ftp.hp.com/pub/caps-softpaq/cmit/whitepapers/HPBIOSSetup.pdf
- https://uefi.org/specs/ACPI/6.5/02_Definition_of_Terms.html
- https://github.com/torvalds/linux/blob/v6.12/drivers/bluetooth/btusb.c
- https://github.com/acidanthera/BrcmPatchRAM/blob/2.7.2/BrcmPatchRAM/BrcmPatchRAM3.cpp
