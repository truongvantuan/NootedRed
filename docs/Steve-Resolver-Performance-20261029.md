# Resolver performance migration

Adapted from Steve snapshot fa08caf2005ba4fc09d4250c33e3340d287ca5d3,
primarily ac69f84 and f08df66. Existing exact-profile selection, complete
function/reference checks, ambiguity rejection and read/candidate budgets remain.

Changes:

- Read dense cache path metadata through a bounded 4 KiB workspace window while
  still checking the entire image directory, including late duplicates.
- Add local buffer ownership: nested metadata lookups cannot overwrite a live
  text scan; nested scans use the bounded local fallback. Ownership releases on
  every return path. No cross-process or persistent positive-match cache is added.
- Use a common fixed-byte anchor to skip impossible prefix candidates. Both
  legal prefixes must contain that same unmasked byte. Signed-byte kernel and
  standard libc memchr models are tested for all byte values.
- Compare ordered relocation masks with a forward cursor; unordered metadata
  retains the linear check. Duplicate/overlapping fields retain their meaning.
- Generate deterministic anchor rarity ranks from the local full-function corpus;
  the fork's different corpus is not copied as an assumed current ranking.

Evidence:

- All 52 workflow host checks pass. The old scanner baseline and both optimized
  memchr models each pass 13,822 anchor/cursor cases with fatal sanitizers.
- Metadata fixture reads fall from 2,185 to 265. Nested metadata/scanner buffer
  ownership, whole-directory validation, window edges and faults are exercised.
- In the actual read-only cache-file comparison, all six APUs and both blend
  selections return the same plans. Two-pass reads fall from 8,016 to 1,636;
  median CPU time across three alternating runs falls from 10.6615 to 2.35 ms.
  These include file-reader overhead and are not GPU or kernel benchmarks.
- The own-process passive probe accepts the same current profile with leaf RX,
  reducing reads from 4,021 to 831. Surface remains uninstalled on the baseline.
- RELEASE builds pass. Compiled visible direct stack chain: 4,464 bytes;
  largest reachable frame: 1,592 bytes; wrapper: 72 bytes. Native kernel functions
  and indirect callbacks are excluded; this is not a whole kernel-stack bound.

Evidence is under build/steve-metadata-buffer-20261029/. Hardware acceptance,
startup performance and the wider migration remain incomplete. The opt-in FVRC
cache and the upstream display-framework rewrite are not included.
