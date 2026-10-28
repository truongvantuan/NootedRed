# Local Phantom first-boot verification

27 October 2026, macOS 15.8.2 (24H232), boot UUID
`CAB3426F-353D-4F60-B44B-82944E9E6B90` at 19:30:22.

## Confirmed

- Exact local RELEASE Phantom 1.0.2 UUID
  `1DF62D63-DFBD-3ABE-99B2-D7575979F468` is visible in the loaded-kext list.
- Its IORegistry service is active with `VersionInfo=REL-MDL-2026-10-27`.
- `kern.securelevel=1`, `kern.hv_vmm_present=0`. The former is the plug-in's
  reported value, not proof of enabled SIP. csrutil still reports the custom
  reduced-security configuration; no SIP setting was changed.
- NootedRed RELEASE `382D20A6-DBBB-3E0E-8282-CDCE0420B1BF` remains loaded.
  Complete private Metal page/SubmitGuard byte checks and payload RX protection
  pass; WindowServer's two applied markers remain set. GL page checks pass.
- No GPU reset/hang was observed in the passive capture. NotificationCenter's
  904 signed pages match. No new rendering/video workload was submitted.
- User confirms League Client reaches its lobby without a Vanguard error.
  In-match/practice-session verification has not been completed.

## Bluetooth failure requires isolation

User reports Bluetooth does not work on this boot and describes a similar
power-off/on detection problem in Linux. This is relevant to a power-state or
firmware hypothesis but does not establish that both failures share a cause.

macOS does enumerate the DW1560 USB Bluetooth device, `0a5c:216f`, and the
BrcmPatchRAM3 service matches its expected firmware key. All existing Bluetooth
kexts are loaded. The upper stack nevertheless reports controller address NULL,
firmware `v0 c0`, and power off. BlueTool reports missing btaddress/bootdata.
Successful firmware initialization is not verified merely by kext matching.

Repeated bluetoothd EXC_GUARD user-fault reports and changing daemon PIDs are
recorded after 19:30. Some reports are marked simulated; PID changes also show
repeated service restarts. No claim is made that every report is a distinct
fatal crash. The previous working-boot evidence did not have this report series.

Phantom was newly enabled on this boot. Its global legacy query behavior remains
a possible contributor; the Linux history does not exonerate it. There is no
controlled A/B result yet. Do not change firmware delays, USB mapping, reset
pairings, or replace the wireless stack based on this capture alone.

Recommended next control: save work, shut down normally, disconnect AC and
powered USB accessories for 30–60 seconds, reconnect and boot directly into
macOS using the same EFI. This is a diagnostic power-state test, not a proven
repair. If Bluetooth remains broken, compare a Phantom-disabled boot under the
same conditions. No shutdown, service reset or EFI modification was performed
by this verification.

Broadcom RAMUSB firmware is volatile and requires an upload at startup/wake;
this makes firmware state worth checking. Source:
[BrcmPatchRAM documentation](https://github.com/acidanthera/BrcmPatchRAM).

## Evidence

`build/phantom-review-20261027/boot-20261027-1930/` contains the summary,
Bluetooth controller/USB data, daemon report timeline, kernel/BlueTool logs and
loaded service evidence. Graphics byte-check capture:
`build/upgrade-hangs-24H232-20261027/boot-20261027-193400/`.

This confirms boot/loading and League lobby access only. It does not establish
full game compatibility, Bluetooth reliability or production readiness.
