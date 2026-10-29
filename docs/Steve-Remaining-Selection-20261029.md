# Remaining fork features: compatibility selection

Review universe: Steve master fa08caf2005ba4fc09d4250c33e3340d287ca5d3.
The first surface candidate failed to activate; corrected RELEASE 9c90257 is
staged in internal EFI. This selection does not replace its pending boot and
functional acceptance. No additional kernel behavior is enabled by this review.

| Component | Finding and decision |
| --- | --- |
| Buffered metadata, relocation cursor, common-byte anchor | Adapted in 7ce9282 with local nested-buffer ownership and full validation retained. Existing measured read reduction is documented separately. |
| Verified known locations | Local exact-cache resolver already uses generated function RVAs only after pinned UUID validation and still checks whole functions and targets. Retain that implementation for the current surface profile. |
| FVRC bounded resolution cache | New capability for generic cross-process searches. Host tests pass. A read-only actual-cache benchmark now demonstrates substantial savings for generic guard scans, so select this for a separate opt-in guard integration. This is not evidence of an additional gain over our pinned exact-location surface path. Do not silently enable `-NRedFVRC` or represent this cache as imported. |
| FVRC mapping proof | Uses current text layouts, read-only true-shared mappings, no shadow/private page, shared object identity and full known-function verification; cached records contain relative locations rather than map pointers. These are useful constraints, not substitutes for current bytes. Kernel mapping-query costs and behavior after local COW remain to be measured before integration. |
| Capability ledger | Explicit eligible/prepared/installed/observed/failure states are useful diagnostics. The upstream ledger is keyed by map and has removeMap, but final destruction integration remains an upstream validation limit. Retain local per-call map leases and boot-lifetime halt on unverified rollback; avoid a second persistent map ledger without lifecycle closure. |
| Display/video coordinator | Local code already has one native syscall route and one serializing map lease. Adding a second coordinator would duplicate ownership. Retain the existing owner and adapt dependency ordering there. SubmitGuard-first surface installation is already tested. |
| Display plan/manifests | The local complete-function planner already checks the current build's corrected superclass reference, all six APUs, scratch/SRD, independent blend ownership, mixed-state rejection and precommit revalidation. Do not replace it with the fork's older Sequoia identity assumptions. |
| Page/transaction/trampoline backends | Keep one local GL page owner and the shared private-memory backend used by surface/media transactions. Rollback verification and permissions are covered by real adapter fault injection. Surface needs no extra executable allocation; video/SubmitGuard payloads retain their existing reachability handling. A separate resource registry adds lifecycle obligations rather than a current missing surface function. |
| Evidence state | Preserve the distinction between installed bytes, functional output, physical wake and release validation. Properties alone cannot mark hardware acceptance. The new initial/runtime build diagnostics expose the startup gate error instead of reporting Requested=0 for a present argument. |
| Shared-region latency diagnostic | Adapted as tools/shared_region_latency.c with strict bounded arguments, JSON output and correctly defined nearest-rank percentiles. This is a user tool, with no extra kernel route or boot option. |

## Evidence gathered in this review

The isolated upstream tests test_fvrc_registry.py, test_fvrc_hot_path.py and
test_fvrc_video.py passed. Their actual scope includes bounded publication,
conflicting entries, concurrent snapshots, ASLR relocation, complete known-RVA
verification, dirty/object/layout fallback, code corruption and read budgets.
These are synthetic host fixtures. They do not test macOS scheduler behavior,
actual long-lived shared-cache mappings or hardware rendering.

Logs and the syscall baseline are in build/steve-selection-20261029/.
Eight calls on the running 7ce9282 boot measured 0.008–0.018 ms. That build has
SurfaceFix disabled by the early gate, even though the argument is present.
The executable has already been initialized by dyld before the first sample;
this is not a cold-start measurement, an unhooked control or a GPU benchmark.

The corrected candidate must pass passive bytes/leaf-RX/WindowServer checks,
normal bounded GL/Metal/compute/video outputs and user-observed stability.
Genuine system sleep/wake requires a separate readiness check and OS transition
evidence. The separate opt-in codec guard path still needs its own hardware
acceptance; do not combine that first test with the surface boot.

## Sources

- [Verified cache](https://github.com/steve12311/NootedRed/blob/fa08caf2005ba4fc09d4250c33e3340d287ca5d3/NootedRed/VPF/VerifiedResolutionCache.hpp)
- [Mapping proof and keys](https://github.com/steve12311/NootedRed/blob/fa08caf2005ba4fc09d4250c33e3340d287ca5d3/NootedRed/VPF/ResolutionIdentity.hpp)
- [Fast resolution](https://github.com/steve12311/NootedRed/blob/fa08caf2005ba4fc09d4250c33e3340d287ca5d3/NootedRed/VPF/FastResolution.hpp)
- [Capability ledger](https://github.com/steve12311/NootedRed/blob/fa08caf2005ba4fc09d4250c33e3340d287ca5d3/NootedRed/VPF/CapabilityState.hpp)
- [Latency probe](https://github.com/steve12311/NootedRed/blob/fa08caf2005ba4fc09d4250c33e3340d287ca5d3/tools/probe_shared_region_latency.c)

## Actual-cache codec-guard comparison

The local generic guard resolver and the upstream cold/hot resolvers accept the
same current 24H232 cache files. Their four guard entry offsets, original bytes
and complete bound payload match byte-for-byte, including both upstream warm
passes. FVRC's cache remains separate from each process's payload address.

| File-backed path | Accounted reads | Reader calls | Bytes requested | Observed CPU time |
| --- | ---: | ---: | ---: | --- |
| Local generic cold | 1,808 | 1,813 | 5,430,827 | 6.337–9.213 ms |
| Upstream generic cold | 1,648 | 1,649 | 5,422,763 | 5.667–5.850 ms |
| Upstream FVRC warm | 403 | 404 | 395,070 | See saved individual samples |

The warm path performs one modeled mapping query per pass. Mapping identity and
share mode were simulated for the file-backed reader; these are not measured
kernel VM costs or a proof of live shared-object identity. CPU time includes
file-reader overhead and only a few samples. The byte/read reduction and exact
plan agreement are the useful evidence; these numbers do not predict FPS.

Evidence and reproducible C++ sources: build/steve-selection-20261029/guard-benchmark/.
The next cache candidate should target the generic guard resolver, retain full
native/patched function and reference verification, keep payload binding private
per call, and remain opt-in. The staged surface build and its config are unchanged.
