# AppleALC layout audit — 27 October 2026

Keep layout 11; no EFI changes were made.

SysReport and live IORegistry identify Realtek ALC897 (10EC:0897), subsystem
103C:872E, on the HP EliteDesk 405 G6 Desktop Mini. AppleALC 1.9.9 is loaded.
HDEF has alc-layout-id 11 and internal AppleHDA layout-id 7; the codec profile
comment matches upstream layout 11 (Gigabyte Z590M). These are not two competing
AppleALC selections. The user confirms the PC speaker works, and macOS selects
Internal Speakers as the default output.

Upstream ALC897 profiles cover other boards and laptops; none is explicitly
identified for HP 872E. Layout 23 contributed by weachy targets Chuwi CoreBook
X14. Authorship does not establish matching HP pin wiring. No alternative has
a demonstrated advantage here. Layout numbers select routing configurations,
not quality/performance tiers.

The best verified choice for the currently used speaker is 11. Physical headphone
switching, microphone recording (if used), volume/mute and post-wake audio should
be checked before declaring all audio functions verified. Device names alone do
not prove physical presence or usable recording. A custom layout would require
pin/connection evidence and a concrete failure to correct.

Evidence: build/audio-layout-audit-20261027/.
Source: https://github.com/acidanthera/AppleALC/blob/master/Resources/ALC897/Info.plist
