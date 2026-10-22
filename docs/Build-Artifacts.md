# Per-Branch Build Artifacts

Builds are separated by git branch so switching branches cannot overwrite another branch's kext or zip.

## Usage

```sh
tools/build-branch.sh -y
```

The script detects the current branch, sanitizes it, and invokes xmake with
`NRED_BUILD_BRANCH`. Artifacts land under:

```text
build/branches/<branch>/<platform>/<arch>/<mode>/
```

For example:

```text
build/branches/feature-tahoe-26.7.1/macosx/x86_64/release/NootedRed.kext
build/branches/feature-tahoe-26.7.1/macosx/x86_64/release/NootedRed-0.9.0-RELEASE-20261020-231422.zip
```

A detached HEAD uses `detached-<short-sha>`. To override:

```sh
NRED_BUILD_BRANCH=my-test tools/build-branch.sh -y
```

The wrapper appends the local build time to the archive name (`...-YYYYMMDD-HHMMSS.zip`), so repeated
default builds never silently overwrite each other. Direct `xmake -y` (without the wrapper) uses
`build/branches/shared/...` and keeps AppleForge's canonical archive name; the wrapper is the supported
interface for per-branch, timestamped output.

Only archives written by the current invocation are timestamped. Older canonical archives from another
version or build mode are preserved.

## Why

The kext and zip are versioned by branch (for example the stable 15.8.1 build and the experimental
26.7.1/VDA builds). Keeping them under one branch-specific directory avoids accidentally installing or
sharing a kext from another branch.

## Build setup used for 1.0.0

Weachy's workflow (`.github/workflows/main.yml` on `weachy/NootedRed`) clones AppleForge with its
submodules, installs xmake, and configures each build mode separately. The local build follows the
same AppleForge rules and adds the branch wrapper for timestamped output:

```sh
git clone --recurse-submodules https://git.chefkiss.dev/AppleHax/AppleForge.git ../AppleForge
xmake f -m debug -a x86_64 -y
sh tools/build-branch.sh -y
xmake f -m release -a x86_64 -y
sh tools/build-branch.sh -y
```

The validated local toolchain is xmake 3.1.2, Apple clang 17.0.0, AppleForge
`bfb2efb185a6c5b758596399e7997612bdd7ca9f`, Lilu
`0515f40b7f2a096adc85e832a4c6104fbd07f936` and MacKernelSDK
`3f750085caa17ec3a7880f11c11bf4f48cd6a164`. Command Line Tools suffice even though xmake's optional
Xcode SDK detection reports `no`; the kext uses MacKernelSDK headers and libraries.

xmake 3.1.2's ZIP helper opens a nonexistent temporary stdin file when its input is a string.
For this toolchain, the local AppleForge `xmake/rules/AppleForge.lua` passes `{ "." }` instead of
`"."` as the second argument to `archive.archive`. This creates the input list before invoking ZIP
and leaves the compiler flags and kext contents unchanged.

For Debug crash symbols, retain the matching dSYM:

```sh
xcrun dsymutil build/branches/master/macosx/x86_64/debug/NootedRed.kext/Contents/MacOS/NootedRed \
  -o build/branches/master/macosx/x86_64/debug/NootedRed.kext.dSYM
```
