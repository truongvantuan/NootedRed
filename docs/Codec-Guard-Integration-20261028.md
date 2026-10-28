# Codec guard integration: validated primitives

Source: steve12311 31fcc87 and its preceding codec guard commits. These components
are now in the local tree and wired into the existing shared-region hook behind
the experimental `-NRedVCNSafety` gate. That gate is off by default and has not
been enabled in EFI. This is not a hardware-verified driver fix.

## Imported and adapted components

- Bounded shared-cache reader, typed section resolver and complete function
  guard resolver, plus generated Darwin24/25 guard references.
- Guard-only patch descriptor types, avoiding the fork's complete competing VA
  adaptation table/module. No second validation/shared-region hook is registered.
- Native CPU guard payload generation/fixtures and resolver tests.
- Shared-region transaction executor, adapted to verify every rollback write by
  readback before deciding that earlier safety guard entries can be removed.
  A successful restore call with incorrect bytes or an unavailable read is not
  classified as verified rollback. Unverified media rollback retains earlier guards.
- Exact 24H232 media planner and generated layout: all ten pages must match full
  original or full target images; mixed, corrupt, missing, duplicate and overlapping
  targets reject. Rejected plans expose no usable site count. Valid plans have
  fourteen media sites; a future combined transaction prepends four guard sites.

No per-page reference match is treated as permission to write an unrelated mapping.
The media layout derives from the new signed exact current-build headers; the
cache reader and metadata remain bounded and read-only during planning. Workspace
contains large page buffers and must be heap allocated in the kernel installer.

## Guard policy

Actual hardware-target encoder requests/configure/per-frame inputs are checked
for even dimensions and bounds, including visible/storage containment. AVC
width minimum128, HEVC minimum130, height minimum128, maximum4096x2304. Actual
H.264 SPS is checked per frame for profiles66/77/100, 4:2:0 and8-bit components.
This does not enable HEVC Main10, fix all HEVC hangs or increase codec limits.
Native errors and unaffected devices remain native. The local Main10 opt-in,
profile/build ABI checks, GfxOff, complete pitch correction and native teardown
policies are unchanged.

## Evidence

All41 workflow host invocations pass. New evidence includes:
- 67473 actual native/payload CPU cases for each Darwin24 and25 reference.
- 17098 guard resolver cases per major, ASan/UBSan with fatal sanitizer errors.
- Exact media page plan positive/negative and all-page mutation tests.
- Transaction failure injection, including silent rollback corruption and
  guard retention when original bytes cannot be verified.
- Local imported guard resolver accepts this host's actual24H232 cache in a
  read-only diagnostic. The older fork full VA adaptation plan still rejects a
  moved AppleGVA data reference, as documented in the previous follow-up.

CPU callback substitutes never create GPU objects. Full-function and page matches
are reference evidence, not actual decoder/encoder output. Logs and import hashes:
build/steve-codec-guards-20261028/.

## Required runtime ownership integration

Do not merely invoke the guard after the existing global VA pager has already
made hardware adaptation available. On the supported target, the combined path
must own guard and media installation privately within the existing map lease:

1. Validate policy, actual cache identity, supported device and ready kernel bridge.
2. Disable competing global VA/GVA mutation for this selected private path;
   preserve existing GL/Metal and unsupported/older-OS behavior.
3. Resolve complete guard functions, typed references and exact media pages.
4. Check all sites and VM protections; allocate and seal/read back the guard RX
   page; bind and revalidate entry plans before writing.
5. Install guards before media adaptations in one reversible transaction.
6. Repeated calls must verify the entire installed guard page, bound entries,
   media pages and RX permissions. Markers alone never authorize skipping checks.
7. On incomplete rollback, retain reachable guard storage, isolate failure and
   stop hardware testing. Do not free referenced code or fall back to an unguarded
   adaptation. State/lifetime handling must avoid stale map-pointer reuse.
8. Keep one existing shared-region hook, including when video is enabled with
   SubmitGuard/LegacyBlend opted out. Preserve native syscall ordering/results.

## Implemented private adapter checkpoint

`MediaSafety.cpp` now implements that ownership sequence for Darwin24 build
24H232, the exact current cache UUID and the existing VCN2.2 device allowlist.
The gate additionally requires an existing video-mode request and the local
profile/external-video checks. It suppresses global VA/GVA pager registration
before routing the private path. If routing or readiness fails, this selected
path leaves media stock; it does not fall back to unguarded adaptation. GL/Metal
owners and default/older-build media routing remain unchanged.

The adapter rechecks all ten original media pages immediately before code-page
COW, after allocating, sealing and reading back the guard payload. Four guards
precede fourteen media writes. Repeat calls verify full functions, typed targets,
guard payload and complete media pages again. Existing per-map leases serialize
our installers; this is not a stop-the-world guarantee against unrelated writers.

An incomplete rollback retains the possibly reachable payload and halts further
private media installs for the boot. This deliberately uses no persistent map
pointer identity or new map-destruction hook. It is coarser than upstream's map
quarantine and does not undo patches already installed in other processes.
Published user pages are owned by their address space until native map teardown.
VM deallocation failures can leak an unpublished page; they cannot justify freeing
potentially referenced guard storage. Stop hardware testing after a halt marker.

Evidence: all44 workflow host checks pass. The actual adapter runs under fatal
ASan/UBSan in 241 cases covering policy combinations, repeat installs, every
write/protection failure, allocation failures, maximum-RX sealing, payload
corruption, a changed non-site page byte between planning and publication,
silent rollback corruption, guard retention and refusal of later transactions.
The actual shared-region wrapper is also exercised with video-only routing,
unready bridge, FairPlay exclusions and native syscall failures/results.

The production compile flags yield a 72-byte wrapper frame, 1576-byte largest
reachable frame and 4744-byte visible direct call chain across UserPatches and
MediaSafety. This excludes native kernel implementations and indirect callbacks;
it is not a bound on total kernel stack usage. The RELEASE build passes.

No new kext or boot argument has been installed. Runtime patch-byte validation,
valid hardware encode/decode output, process startup cost and real sleep/wake
acceptance remain required. Malformed inputs stay CPU-only until the installer
and normal hardware workloads are accepted. Broader SRD/scratch and VPF lifecycle
work remains separate; importing the transaction executor is not their adoption.
