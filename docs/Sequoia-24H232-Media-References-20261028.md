# Exact 15.8.2 media reference integration

This supplies the missing current-build references needed for the active Steve
fork migration. It does not yet install the fork's codec guards or VPF framework.

Inputs: macOS15.8.2 build24H232, cache UUID90DB0DEB-2344-3601-B011-B87312D74CFB;
VA7.0.26 image5D90FED3-BCBF-3475-9F4B-8FC00026D3AB; AppleGVA113.56 image
BCB9A0BE-8EB3-361A-B5B1-24767FFC1774.

Both existing generators derive complete pages and patch sites from the target
cache. Generation was directed to temporary files with the existing explicit
live-cache override; no override is accepted as integrity evidence. Every one
of the nine VA pages and the GVA page was subsequently compared to the source
file and its embedded CodeDirectory hash. All ten matched without normalization.
The checker does not validate the CMS trust chain or claim hardware correctness.
Reproduction with the committed target headers and both --check modes succeeds.
No cache or system binary is written.

New generated headers are separate from the existing 24H32 headers. Registered
VDA tables can carry an exact build qualifier. At processPatcher (device/profile
known), a qualified match selects only that build's VA/GVA pair; otherwise the
previous default pair remains selected. Empty/unknown builds keep the previous
fallback, whose complete-page checks remain mandatory. Registration capacity
increases from two to four table descriptors, while native page/site capacities
remain unchanged. Only one pair is appended, avoiding page-cap truncation or
overlapping owners. NRedVDATableRevision2 reports qualified selection; revision1
is the default path. The ready VCN bridge/profile, FairPlay exclusion and
Main10 opt-in policy are unchanged.

The new VA table includes the existing complete 37-byte source-pitch correction,
48-byte encode feedback/status strides and GFX9 family/engine/address-library
adaptations. GVA redirects only the verified no-Intel fallback to the native AMD
tail: 0x7ffa0669641b branches to0x7ffa0669644b instead of0x7ffa066967f7.
It preserves the hardware query and the native guarded/special-machine paths.
The old tables, old pitch reference and other OS paths are not removed.

The media verifier recognizes both cache UUIDs, chooses the corresponding VA
reference, and for24H232 also checks the entire relocated GVA page. Missing,
mutated, stock or cross-build pages fail. Its new probe captures all ten pages
from its own private mapping using --cache-only without GPU commands. The new
probe was compiled separately, leaving previously pinned build/tools binaries
unchanged; deployment metadata will need the new probe identity before video
exercises. No hardware/video result is inferred from reference generation.

Validation: all36 existing host invocations pass, including new qualified-table
selection and24H232 page mutations. RELEASE and the separate probe build pass.
Both generators reproduce target headers. Source logs, signed-page results,
cache-only snapshot and test reports: build/steve-media-reference-20261028/.
The current installed EFI is unchanged. Runtime activation, codec guards,
full video output testing and the remaining fork candidates are still pending.
