# PAT patch review — 27 October 2026

The mounted internal EFI has exactly one enabled PAT entry eligible for macOS
15.8.1 / Darwin 24.6.0: Algrey / Zormeister, macOS 15.0+, range Darwin
24.0.0–25.99.99. Its complete patch fields match current AMD Vanilla. All four
PAT entries match upstream in every field except the Enabled selection on the
older pair. No EFI changes were made.

| Patch | Config enabled | Kernel range | Eligible for current Darwin |
|---|---|---|---|
| Algrey, original | No | 17.0.0–23.99.99 | No |
| Shaneee, original | Yes | 17.0.0–23.99.99 | No |
| Algrey / Zormeister, Sequoia+ | Yes | 24.0.0–25.99.99 | Yes |
| Shaneee / Zormeister, Sequoia+ | No | 24.0.0–25.99.99 | No |

Two Enabled entries do not mean both apply on this OS: kernel ranges are
mutually exclusive. Do not enable both alternatives for Darwin 24. Keeping
the pre-Sequoia pair is harmless for this boot and preserves its historical
OS selection; no older-OS boot compatibility was tested here.

PAT controls memory cache attributes. The linked mikigal guide selects
Shaneee by default for potential AMD graphics performance, with HDMI/DP audio
and NVIDIA caveats. AMD Vanilla defaults to Algrey for compatibility and also
documents the Sequoia-specific pair. The mikigal guide explicitly excludes
integrated GPUs from its hardware coverage, so its performance preference is
not a measured recommendation for this Renoir/NootedRed installation.

Retain the currently verified Algrey selection for the production baseline.
This is a stability preference, not evidence that Shaneee cannot improve this
APU. A performance trial would need changing only the Darwin-24 alternative
pair, preserving the new production boot arguments and comparing graphics,
video, display audio and sleep/wake under controlled conditions. No benchmark
or actual PAT MSR read was performed in this review. Configured eligibility
and upstream byte equivalence do not independently prove the live MSR value.

The Sonos AirPlay response delay was separately traced to a 2000 ms sender
buffer and reduced to a verified smooth 500 ms. That observation provides no
basis to attribute that delay to PAT or to change PAT as an AirPlay fix.

Evidence: build/pat-review-20261027/SUMMARY.json and PAT-config-reference.plist.
The EFI configuration hash is recorded in SUMMARY.json.

Sources:
- https://github.com/mikigal/ryzen-hackintosh/blob/master/README.MD#pat-patch
- https://github.com/AMD-OSX/AMD_Vanilla#information-on-the-fix-pat-patch
- https://github.com/AMD-OSX/AMD_Vanilla/blob/master/patches.plist
