# Sequoia 15.8.2 post-update verification

Verified 27 October 2026 on macOS **15.8.2 (24H232)**, Darwin 24.6.0.
Boot UUID: `B6B2839C-1560-4D97-A2FD-955C7EFD0896`.

## Checks passed

- All 123 internal EFI files match the verified pre-update manifest; OpenCore
  1.0.9 configuration validation passes. No EFI or driver changes were made.
- Expected NootedRed RELEASE UUID `C6B65316-A326-3F6C-A3D6-79611B43677D`
  and local VirtualSMC startup-race build UUID
  `556F477A-93E6-319A-9E07-4194AD44DCF5` are loaded.
- VirtualSMC readiness gate 1 / flags 3; watchdog daemon has run once and its
  user client belongs to that daemon.
- Production boot arguments remain `-NRedGLFix -NRedVCNNoGfxOff -NRedVDA`.
- All 36 PCI functions detected. Renoir reports 1.5 GB VRAM and Metal 3;
  the monitor runs at 2560×1440, 144 Hz.
- Three standalone OpenGL patch pages match the expected device-specific bytes.
- DW1560 Modern Wireless root-patch metadata records 24H232 and was regenerated
  at 15:32:58. Wi-Fi is the default route on en1 and an HTTPS request bound to
  en1 succeeds. Bluetooth is powered on with FC750RBT connected.
- Internal Speakers is the default output. User confirms desktop/menus, usual
  USB ports, speaker, Wi-Fi and Bluetooth all work normally.
- NotificationCenter's 904 signed code pages match, with CPU observed at 0.0%.
- No GPU reset/hang or current-boot crash report observed in the captures.
  Retained dmesg has zero allocation-failure lines; bounded retention is not
  proof that no warning ever occurred.
- Sonos latency preference remains 500 ms; no new AirPlay listening test done.

## Compatibility gap found

The system shared-cache UUID changed from
`42EC2890-BC40-317E-BB27-45142BFF7F26` to
`90DB0DEB-2344-3601-B011-B87312D74CFB`.

LegacyBlend and SubmitGuard enabled markers are present but their applied /
WindowServer-applied markers are absent. Their 15.8.1 reference-byte checks
fail. The exact old full Metal control page is also absent from the collected
24H232 Metal image. This needs analysis of the actual new image, not just a
cache UUID substitution. Base Metal support reported by macOS does not verify
these optional driver patches.

The VA/GVA validation tool correctly rejects the old shared-cache identity;
`NRedVCNUserApplied` is absent. VCN kernel ABI/native-load markers are ready,
but a family fallback is selected (`NRedVCNDataIdentityAvailable=0`, variant 7).
This is not evidence of successful hardware decoding or encoding. Video
user-space patch application and functional output remain unverified.

No new GL/Metal/video GPU workloads were submitted during this verification.
The correct next step is to derive/review 24H232 references, verify patch bytes,
then run bounded captured functional tests. Do not relax byte guards to force
old offsets to apply. The earlier intermittent Zalo HEVC hang remains unresolved.

## Sleep and recovery limits

Current boot Sleep/DarkWake/UserWake counts are 0/0/0. A real sleep/wake test
has not been performed, and prior readiness was deferred. Test only when ready.
Verify actual OS transitions, desktop, devices and automatic Wi-Fi reconnect.

The full independent backup was deferred before updating. The local EFI/source
backup is preserved, but is not a full personal-data backup or guaranteed OS
rollback. No claim of complete production validation is made for 24H232 yet.

## Local evidence

Study: `build/update-sequoia-15.8.2-20261027/`.

- `POST-UPDATE-VERIFICATION.json`
- `post-update-20261027-181829/SUMMARY.json`
- `feature-bytes-24H232/SUMMARY.json`
- `EFI-post-update-comparison.json`
- `Metal-24H232-reference-comparison.json`
- `nred-compat-15.8.2/manifest.json`

The compatibility dataset contains Apple binaries; keep it local. It was
collected with NootedRed patches active and is explicitly flagged accordingly.
Do not generate a new stock patch dataset from it without accounting for the
patched page cache; pristine offline image data is preferable.
