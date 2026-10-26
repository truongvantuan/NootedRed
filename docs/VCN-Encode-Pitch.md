# Sequoia VCN2 encoding investigation

The correction is runtime-verified on the 17:35 boot, DEBUG UUID
`A501FFE9-7952-3A7A-83A7-19BBDA54E22C`. Both codecs pass hardware decode/encode
pixel checks, and GL/Metal rendering and compute pass. Three browser video
start/stop/fullscreen cycles pass. A recorded system sleep/full wake is followed
by passing checks of all seven native workloads, with no observed reset or hang.
The failing comparisons and correction guards are retained below.

On the 2026-10-23 14:01 full-VDA boot, our DEBUG UUID
`D687C8DC-274B-3E38-AF70-0D798EF38460` passes hardware H.264 and HEVC decode:
three 1280×720 8-bit frames per codec exactly match independently selected software
decoders. There are no observed GPU resets or GPU/WindowServer reports.

H.264 hardware encoding returns three decodable frames, but the decoded pixels
are corrupted (mean absolute error 75.5203, maximum 192). HEVC encoding is not
submitted after this failure. The user confirms responsive desktop and normal menus.

A controlled comparison uses VideoToolbox's compression-session source pool instead
of separately allocated CVPixelBuffers. All three inputs are IOSurface-backed,
have 1280-byte CPU strides and pass CPU input readback; timestamps remain ordered.
Output has exactly the same pixel error. Software H.264 encoding passes with both
input allocations; software HEVC passes with pool inputs. This narrows the issue
but does not identify the encoder's internal texture layout or GPU fault cause.

A later boot at 14:41 retains the old NootedRed binary and loads the three added
sensor/TSC kexts described below. A single bounded H.264 comparison reproduces the
same mean/max pixel error, again with no reset or new report. Its 32×18 luma samples
fit a 1280-byte firmware pitch reading a 2048-byte backing stride much better than
the other tested stride hypotheses (sample mean error 1.345 versus 70.427 for 1280).
This is a model-based inference from sampled pixels, not a direct read of the
encoder's texture object or proof that the candidate has fixed it.

The live probe mappings verify all eight existing VA patch pages, including all
three 48-byte feedback-stride patches. Ordinary cache-file reads showed stock
feedback functions; they were insufficient to establish the code in a process's
validated mappings. The verifier now checks all nine complete VA pages, including
the candidate below, before submitting video work. These snapshots are from the
probe process; they are not a dump of VTEncoderXPCService's private address space.

## Candidate and limits

The exact Sequoia function `Vcn2Encoder::setEncodeParams` at `0x7FFB0864CAC4`
calculates source pitch using encoder width:

```text
pitch_elements = align_up(width * element_bytes, 256) / element_bytes
chroma_pitch_elements = pitch_elements / 2
```

It does not use the stored texture byte stride at texture offset `0x80`. Other
native texture consumers use that field to create surfaces; offset `0x84` is the
element size. A 256-byte width estimate can differ from the actual texture stride.
This also appears in the Steve fork's encode correction, reviewed separately in
[Steve12311-Review.md](Steve12311-Review.md).

The candidate replaces only the 37-byte pitch block at function+`0x31`:

```text
pitch_elements = texture_stride_bytes / element_bytes
chroma_pitch_elements = pitch_elements / 2
```

Both native callbacks, the remaining parameters and surrounding function are
preserved. This does not change VRAM, page tables, encoder capabilities or decode
code. The before/after comparison now verifies the correction for the original
corruption reproducer; broader workloads and longer use remain separate checks.

`tools/gen_vcn_encode_pitch.py` pins cache UUID
`42EC2890-BC40-317E-BB27-45142BFF7F26`, VA-driver UUID
`662187E4-9F38-375B-9BF6-CCAC3F60979A`, the complete 138-byte function hash and
the original full 4096-byte page against the subcache's embedded CodeDirectory.
The generated page has no contextual fallback. Registration is restricted to
Darwin 24 and retains the existing VDA/device/VCN-ready/FairPlay gates. It does
not extend this candidate to Sonoma or Tahoe.

`tools/test_vcn_encode_pitch.py` executes the full captured function with production
replacement bytes and CPU-only fake objects. All 45 cases pass under ASan/UBSan;
29 reproduce the width/stride mismatch. Callback arguments, other fields and input
objects remain unchanged. Production page-dispatch tests reject a changed page and
an unready VCN bridge. All 17 workflow host checks pass. DEBUG and RELEASE ZIPs
build and verify. DEBUG now has the runtime evidence below; RELEASE is not boot-tested.

## Deployment and next check

The staged DEBUG candidate UUID is `A501FFE9-7952-3A7A-83A7-19BBDA54E22C`.
Only the USB NootedRed executable was replaced; full-VDA/GFXOFF boot arguments
remain unchanged. The pre-candidate EFI is fully backed up at
`~/EFI-Backups/OPENCORE-before-VCN-encode-pitch-20261023-172046/EFI`.

The configuration changed externally during this session: three entries were
added for SMCRadeonSensors, SMCProcessorAMD and ForgedInvariant. They are preserved,
and their current configuration is included in the backup. Their presence on the
14:41 boot does not resolve the encoding corruption. That later boot provides the
pre-pitch comparison with the added kexts already active. The subsequent 17:35 boot
loads the correction with the same additions and passes functional output checks.

Old GPU/watchdog reports were copied or touched after that later boot. The collector
now prefers their embedded dates over modification times, records timezone-less
dates as local-time inferences and keeps unresolved fresh reports blocking. All 24
retained reports predate this boot by that assessment; current-boot kernel queries
also report zero resets. Original captures are preserved, with a separate provenance
recheck. A GPU-hang message now stops subsequent exercises even without a reset entry.

After rebooting from OPENCORE USB, collect the read-only baseline:

```sh
bash /Users/tvtuan/Github/NootedRed/build/vcn-encode-pitch-20261023/collect-after-boot.sh
```

Require the expected UUID, all rendering and nine VA pages, VCN readiness and a
clean fault baseline before the separate `run-video-test.sh`. It rechecks both
decoders, H.264 encoding and then HEVC encoding, stopping on the first failure.
`run-render-regressions.sh` has passed the combined GL/Metal checks. The user then
requested sleep: macOS records sleep at 17:49:19 and full wake at 17:49:52, with
Sleep/DarkWake/UserWake counters all 1. The user confirms working desktop/menus.
`post-wake-test-20261023-175410-2175` passes Metal render, compute, both codecs'
hardware decode/encode and GL after that transition, with no new reset/hang/report.

The first native encode comparisons report H.264 mean error 0.010725 / maximum 1,
and HEVC mean 0.009268 / maximum 7; both decoders match software exactly. The
browser test passes hardware WebGL 1/2 and three playback/fullscreen cycles with
464 observed video frames. Its three players report VideoToolboxVideoDecoder;
strict hardware selection is verified independently by the native sessions.

Alternative video boot modes and longer media use remain separate requirements.
The user also requested a production EFI audit after feature verification. No
reboot is performed by the agent. Aggregate evidence: `RUNTIME-PASS.json` in the
candidate evidence directory. The exact tested binaries and original probe source
are preserved under `probes-tested/` before adding alternate-mode controls.

Private evidence: `build/vcn-encode-pitch-20261023/PRE-CANDIDATE-EVIDENCE.json`,
`build/vcn-full-20261023/encoder-diagnostic/` and the candidate deployment manifest.
