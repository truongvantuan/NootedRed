# Overnight Steve updates: investigation checkpoint

Latest master observed on 29 October:
fa08caf2005ba4fc09d4250c33e3340d287ca5d3, eight commits after the previously pinned
31fcc87. This is an additional review snapshot, not a wholesale merge or a claim
that the entire migration is complete. Source is isolated under
build/steve-latest-20261029/source/.

| Commits | Change | Local assessment |
| --- | --- | --- |
| 4c0f41d | Shared display manifests, transactions, capability/dependency state, GL page backend, executable-resource lifecycle, display evidence and display/video coordinator | Our code already has one native shared-region call, one map lease and one GL validation owner. The new coordinator is unnecessary for those local owners. Adapt verified ordering/transaction semantics; audit remaining evidence/state behavior separately before replacing working paths. |
| ac69f84 | Sequential relocation checks, buffered metadata paths and scan filtering | Useful independent performance candidates. Evaluate buffer ownership and equivalence before adoption; not installed yet. |
| 7ba8b8d | Resolution counters and a native shared-region latency probe | Diagnostic evidence, not patch authorization or GPU performance. Our own passive surface probe and host measurements remain separate. |
| 31b65c0 | Bounded resolution cache | Needs current mapping/layout identity, concurrency and retained-validation review. No local cross-process match cache is introduced by this checkpoint. |
| f08df66 | Rarity-selected anchor prefilter, including signed-byte kernel memchr handling | Retains full candidate verification in upstream. Test high-byte anchors, masked prefixes, ambiguity and bounds against the local scanner before migration. |
| f7d9ce7 | Cached-location verification | Treat locations as hints and retain full native/patched functions and target checks. Our pinned-UUID exact-location path remains independently tested. |
| cef3ff5, fa08caf | Use verified cached locations in video and Metal | Upstream enables FVRC only with explicit `-NRedFVRC`. Its policy/lifetime dependencies are not automatically compatible with our current owners. Continue evaluation after the current surface checkpoint. |

The new display framework correctly emphasizes SubmitGuard ordering. The local
candidate now requires a requested Metal SubmitGuard to verify before installing
SRD/scratch; failures retain pre-existing independent behavior. That change is
covered by the actual wrapper harness, not just a manifest test.

Upstream validation documentation still explicitly leaves final map-destruction
hooks, long shared-cache matrices and real boot/video/encoding/sleep/WindowServer
acceptance unverified. Those statements are limits on upstream evidence, not a
reason to abandon useful compatible features. Our new paths do not introduce
map-destruction hooks or persistent map-pointer state.

Remaining work is feature selection and equivalent local tests, then measured
runtime acceptance. Source/host checks alone cannot prove absence of regressions.

Source: https://github.com/steve12311/NootedRed/tree/fa08caf2005ba4fc09d4250c33e3340d287ca5d3
