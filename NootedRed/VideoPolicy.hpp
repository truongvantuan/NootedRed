// Shared VDA defaults and backwards-compatible boot-argument precedence.
#pragma once
namespace VideoPolicy {
struct State { bool requested; bool avcOnly; bool hevcEncodeAllowed; bool hevc10Allowed; };
template <typename Check> inline State resolve(Check check) {
    const bool requested = !check("-NRedNoVDA");
    const bool noHEVC = check("-NRedNoHEVC");
    const bool avc = check("-NRedAVC");
    const bool avcEncode = check("-NRedAVCEncode");
    const bool avcOnly = requested && (noHEVC || avc || avcEncode);
    return {requested, avcOnly, requested && !noHEVC && !avc,
            requested && !avcOnly && check("-NRedHEVC10")};
}
}
