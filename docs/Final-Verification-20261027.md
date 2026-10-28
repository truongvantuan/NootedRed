# Final verification — 27 October 2026

The new 14:25 production boot (UUID 891A2A62-6A76-4BE6-B9D9-0063B568767B) passed all completed checks.
This is verification of the recent deployment and observed device operation,
not a claim of exhaustive long-term stability.

## Verified on this boot

- Exact final EFI file manifest, OpenCore 1.0.9 validation and remaining enabled
  kext paths pass. Intel wireless, USBToolBox and UTBDefault bundles/entries are
  absent. OpenCore uses RELEASE binaries; no new OpenCore logs were created.
- Active boot arguments are only -NRedGLFix -NRedVCNNoGfxOff -NRedVDA. VM/VCN
  diagnostic markers are absent. The production logging cleanup is now booted.
- Expected local NootedRed RELEASE C6B65316-A326-3F6C-A3D6-79611B43677D is loaded.
  GL/Metal/shared-cache and video patch byte checks pass; VCN bridge is ready.
  No new GPU workloads were submitted by this passive verification.
- VirtualSMC candidate 556F477A-93E6-319A-9E07-4194AD44DCF5 is loaded with gate
  version 1 and ready flags 3. The watchdog daemon started once and its client
  matches the running PID. No current-boot crash reports were found.
- All 36 PCI functions match the archived user export. All five ACPI table
  hashes are unchanged. The original Desktop export was moved/removed, so its
  archived verified copy was used without requesting a re-export.
- Renoir reports 1.5 GB VRAM and Metal support. Solidigm NVMe SMART is Verified
  and TRIM enabled. NotificationCenter's 904 code pages match its signature.
- Wi-Fi is the default route through en1 and a Wi-Fi-bound HTTPS request returns
  HTTP 200. The user confirms desktop/menus, usual USB ports, PC speaker,
  Wi-Fi and Bluetooth all work normally on this boot.
- Sonos audioLatencyMs=500 persists after reboot. The earlier listening result
  was smooth at 500 ms; 350 ms was rejected. No new AirPlay session was active
  in this capture, so acoustic response on this boot was not re-measured.

No GPU reset/hang or new GPU/WindowServer report was observed during the
collection. The retained dmesg had zero allocation-failure warning lines;
retention coverage does not prove such warnings can never recur. Historical
intermittent HEVC/Zalo failures have not been established as fixed by these
configuration cleanups.

## Deferred or not established

The user explicitly selected Not ready; wait for a final-profile sleep test.
No sleep request was made. This boot records zero sleep/wake cycles. The
previous actual DW1560 sleep/wake pass remains valid evidence for that earlier
boot, not a new pass for this boot. Ethernet cable traffic, SATA-drive I/O,
display audio playback, microphone/jack switching and AirDrop transfer remain
physical tests. No heavy graphics or HEVC/Zalo reproduction was run.

Evidence: /Users/tvtuan/Github/NootedRed/build/final-verification-20261027/boot-20261027-142917. FINAL-SUMMARY.json records the completed checks and
limitations. The read-only Disk Arbitration EFI mount attempt failed; normal
mount succeeded. No filesystem repair or EFI file change was made. The volume
was returned to its initially unmounted state after collection.

## Software Update size question

The user showed Sequoia 15.8.2 offered as a 15.64 GB download. Current Sequoia
15.8.1 uses the root-patched DW1560 snapshot. OCLP documents that a broken
system seal causes full-size OS update downloads instead of small deltas. This
explains the likely full payload size; the exact update asset was not downloaded
or inspected. No OS update was initiated. A 15.8.2 upgrade requires checking
the per-build NootedRed GL/video compatibility and the wireless repatch path
before installing. Do not replace this custom AMD EFI with an OCLP-built EFI.

Source: https://dortania.github.io/OpenCore-Legacy-Patcher/FAQ.html
