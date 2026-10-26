# HEVC image decode investigation — 26 October 2026

The App Store freeze remains a hardware-decoding defect under investigation.
The working `-NRedAVCEncode` profile is a mitigation: it disables HEVC decode
advertisement while retaining AVC decode and the video encoders. It is not a
repair of the failed HEVC path.

## Evidence and attribution

The incident evidence is in `build/freeze-investigation-20261026/`. The first
VCN0Dec timeout occurred while App Store's responsible decoder process was
waiting in the AMD video driver. App Store's main thread was waiting for
ImageIO/CMPhoto HEIF tile decompression. An AVC preview was also active, so the
first failing compressed packet cannot be identified conclusively from those
logs.

The pinned Weachy v1.1.1 VA/AppleGVA tables and all 20 macOS 24H32 VCN call-site
records match ours. This rules out a missing merge in those particular tables.
It does not establish whether the failure is inherited or caused by differences
in integration, power management, lifetime handling, or another local change.
No unchanged-upstream controlled hardware comparison has been performed.

## Newly isolated inputs

Study files are in `build/hevc-root-cause-20261026/`.

Thirty-five real HEIF assets were recovered from App Store's cache and examined
without decoding. Their colour images use 8-bit Main 4:2:0. Two assets also
contain an 8-bit monochrome profile-4 HEVC auxiliary alpha image linked through
`auxl` and `urn:mpeg:hevc:2015:auxid:1`. These are genuine cached inputs, but
neither is proven to be the input that caused the incident.

The two candidate source SHA-256 values are:

- Icon: `913c798cb17927eeb082a8f08a01fc190e8769985e524f4e8f93537eda800699`
- Banner: `0516dcface41ccf6686b64513593479959a141f32506fc34da4d33bb1dda5d9f`

`tools/isolate_heif_item.py` produces colour-only and alpha-only container
variants by changing metadata only, preserving all compressed payload bytes
and their offsets. `tools/export_heif_item.py` separately exports the exact
VPS/SPS/PPS and length-prefixed compressed item for a direct VideoToolbox test.
The latter separates ordinary decoder behavior from ImageIO's tile workflow.

`-NRedHEVC10` is not an appropriate first experiment: these candidate items are
8-bit, and monochrome profile 4 is a different capability from Main10.

## Completed checks on the stable boot

- Both combined images and all four isolated variants decode through ImageIO.
- The six cases produce identical pixel hashes with and without the private
  ImageIO software-policy request on this already mitigated boot. This does
  not independently establish which ImageIO decoder was selected.
- All four extracted items decode one frame through VideoToolbox with hardware
  explicitly forbidden. The hardware-status property is unsupported by these
  software sessions; the probe records Apple's documented default-false behavior
  explicitly rather than reporting an observed false value.
- The one-case capture runner passed a software test and found zero current-boot
  GPU failure events before and after that test.
- Metadata/isolation tests cover 318 malformed or truncated cases; item export
  tests cover 217 invalid/truncated cases and verify exact payload extraction.
- Both native probes compile successfully. A hardware request on the current
  mitigated profile is refused before submitting work.

Outputs, input identities and hashes are recorded in `BASELINE-RESULTS.json`,
`ISOLATED-ITEMS.json`, `EXTRACTED-SAMPLES.json`, and `PROBE-MANIFEST.json`.

## Prepared diagnostic profile

`stable-profile/EFI` is a fresh copy of the current internal EFI, read through a
read-only mount. `full-VDA-test-profile/EFI` differs only in `OC/config.plist`:

```
keepsyms=1 -NRedGLFix -NRedVCNNoGfxOff -NRedVDA
```

The kext remains RELEASE UUID `3119DE95-4690-35E6-86A8-869A8ADFC3B7`, SHA-256
`a30a8beadce1a00a69e5cce2e56c581b964223eb9f159d7825f5abeeddeffcf2`.
Using the same binary avoids introducing an additional variable. OpenCore 1.0.9
validation passed. During baseline research no production kext code or EFI file
was changed.

After the user confirmed readiness, the diagnostic config was installed to the
internal EFI. A fresh 111-file backup was verified at
`/Users/tvtuan/EFI-Backups/INTERNAL-before-HEVC-isolation-20261026-142123/EFI`.
Only `OC/config.plist` differs; all other 110 files match the backup. The installed
config passes `ocvalidate`, and the EFI was returned to a read-only mount. The
running session remains on AVCEncode until reboot. `INSTALLATION.json` records
both complete file manifests and the installed config hashes.

## Next physical test

Readiness to install the diagnostic profile has been confirmed; reboot remains
the user's action. Save work; a timeout in a child process cannot contain a
GPU/kernel hang. Boot the installed full-VDA profile and avoid opening App Store
or other video applications before capture. Run the collector first; it submits
no GPU exercise:

```sh
bash build/hevc-root-cause-20261026/collect-after-boot.sh
```

Review the loaded identity, capabilities and current-boot GPU evidence first.
The stable profile can be restored using
`bash build/hevc-root-cause-20261026/restore-stable.sh`, followed by a user reboot.

Start with exactly one colour item:

```sh
sudo -v
python3 tools/run_hevc_isolation.py --api vt --case icon-colour --hardware --yes
```

The runner verifies the loaded kext UUID and artifact hashes, requires kernel
ring capture, and refuses hardware work after an existing GPU failure on that
boot. It records the decoder's hardware selection before submitting one frame.
Review its output and GPU evidence before choosing any next case. Do not loop
through the matrix automatically.

If colour succeeds, separately test `icon-alpha`; then compare a combined image
through ImageIO only after reviewing the previous result:

```sh
python3 tools/run_hevc_isolation.py --api imageio --case icon-combined --hardware --yes
```

For ImageIO, `--hardware` permits the experiment on the full-VDA boot; it does
not prove hardware selection. A separate `--imageio-software` comparison requests
the native `kCGImageSourceUseHardwareAcceleration = false` option in the probe
only. This is not an App Store preference, a global setting, or a kernel fix.

Interpretation remains conditional: a direct monochrome failure would narrow
the format/driver path; a combined-only failure would implicate the image/tile
workflow or interaction between items; passing all candidates would require
finding the actual incident asset and checking concurrency or longer lifetimes.
None of these outcomes can be assumed before running the hardware comparison.

## Results from the 14:30 diagnostic boot

Boot session `B96AD537-6B7B-4A77-B232-CF0700A6FABB` loaded the expected RELEASE
UUID with full VDA. HEVC decode was advertised; Main10's maximum level remained
zero. GL/cache/video page validation passed, with no initial GPU reset or hang.

Three direct VideoToolbox hardware tests passed: the 80×80 colour item, the
282×86 colour item, and a 512×512 tile extracted from a larger grid image.
Each session reported hardware decoding in use and returned one frame whose
active-plane hashes exactly matched the software reference.

The standalone monochrome alpha item's hardware session was refused with
`kVTVideoDecoderUnsupportedDataFormatErr` (`-12910`). No frame was submitted and
no GPU failure followed. This is an unsupported-format result, not a successful
hardware-alpha test or a reproduction of the original hang.

Both small combined images passed ImageIO decoding. A third cached input,
SHA-256 `14244c3eb5f21f0bbdf2f0ea26e5c80873ccdd0c65e9883b84d6a944e3206e15`,
is a 1640×922 grid assembled from eight 512×512 HEVC items. Its complete output
matched between the software-policy request and ordinary ImageIO settings:
RGBA SHA-256 `1699056eb2609700c70575062b74fd3d07f008122b688ba5f02d3b89ff734f0c`.
The ordinary run recorded AppleGVA's `VTTile`, HEVC burst-size and successful
decoder flush/disposal messages. This confirms the relevant tile path was
reached; the probe does not query ImageIO's actual hardware-selection property.

All eight controlled cases finished with zero new GPU failure events. The user
confirmed responsive desktop and normal menus afterwards. Idle drains increased
from 7 to 33, with maximum observed wait still 5 ms. These are bounded test
results, not proof of production stability or a repair of the earlier freeze.
Details are in `CURRENT-BOOT-ISOLATION.json` and the individual test directories.

The user identified the original trigger as the App Store **Home page**.
`tools/capture_appstore.py` now provides a passive, bounded capture of kernel
events, App Store/decoder logs and filesystem activity while the user performs
that workload. It opens no application and submits no GPU work. No claim that
the original defect is fixed follows from the isolated passes.

### Actual Home-page retest

During the armed three-minute capture the user opened Home and confirmed normal
images and window behavior. The run recorded eight AppleGVA `VTTile` messages
and eight successful decoder flush messages, with zero GPU failure events before
and after. Filesystem tracing identified 28 cached HEIF assets read during the
window: 13 grids and 15 direct images. Copies and offline metadata are preserved
under `appstore-home-20261026-144326/`; a read does not prove every corresponding
asset was decoded or that one was involved in the old incident.

These assets' item metadata contains 89 Main 8-bit 4:2:0 configurations and two
8-bit monochrome configurations; none of the traced HEIF assets requires Main10.
This makes enabling `-NRedHEVC10` an unrelated change for this captured workload.

VCN idle-drain counters rose to 47 drains and **10 timeouts**, with maximum wait
250 ms. Home remained usable and no GPU hang/reset occurred. These are real
residual lifecycle warnings, not proof that the decoder wedged. They remain an
investigation lead; no protection was disabled and no timeout was hidden.

The successful Home run with full VDA also limits the earlier mitigation claim:
success with AVCEncode alone cannot prove that removing HEVC decode caused the
improvement. The original freeze is intermittent and has not been reproduced
in this boot. Long uptime, overlapping workloads, teardown behavior and a
different asset remain possible distinctions, not established causes.

No kext or EFI change was made during this post-boot verification. Current
settings remain the explicitly authorized full-VDA diagnostic profile. Stable
AVCEncode recovery configuration and the full EFI backup remain available.
