// Isolate zero-frame VideoToolbox session creation/release, not playback.
// Default: parse format descriptions only. Hardware execution is explicit.
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <sys/sysctl.h>
#include <time.h>
#include <unistd.h>
#include <string>
#include <vector>

static void emit(NSDictionary* value) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    NSMutableDictionary* row = [value mutableCopy];
    row[@"pid"] = @(getpid());
    row[@"monotonic_seconds"] = @(now.tv_sec + now.tv_nsec / 1e9);
    NSData* data = [NSJSONSerialization dataWithJSONObject:row options:0 error:nil];
    fwrite(data.bytes, 1, data.length, stdout);
    fputc('\n', stdout);
    fflush(stdout);
    fsync(fileno(stdout)); // Retain the last completed phase if the GPU freezes the machine.
}

int main(int argc, const char* argv[]) { @autoreleasepool {
    if (argc < 2) {
        fprintf(stderr, "usage: vt_lifecycle_probe fixtures.json [--case normal|small|pair] "
                        "[--software | --hardware --yes] [--invalidate]\n");
        return 2;
    }
    bool hardware = false, software = false, yes = false, invalidate = false;
    std::string selected = "pair";
    for (int i = 2; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--hardware") hardware = true;
        else if (arg == "--software") software = true;
        else if (arg == "--yes") yes = true;
        else if (arg == "--invalidate") invalidate = true;
        else if (arg == "--case" && i + 1 < argc) selected = argv[++i];
        else return 2;
    }
    if ((hardware && software) || (yes && !hardware) ||
        (hardware && !yes) ||
        (selected != "normal" && selected != "small" && selected != "pair")) return 2;
    if (hardware) {
        size_t size = 0;
        if (sysctlbyname("kern.bootargs", nullptr, &size, nullptr, 0)) return 3;
        std::vector<char> data(size + 1);
        if (sysctlbyname("kern.bootargs", data.data(), &size, nullptr, 0)) return 3;
        std::string boot = " " + std::string(data.data()) + " ";
        auto has = [&](const char* flag) { return boot.find(std::string(" ") + flag + " ") != std::string::npos; };
        if (!has("-NRedVDA") || has("-NRedAVC") || has("-NRedAVCEncode") || has("-NRedHEVC10")) return 3;
    }
    NSData* bytes = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
    if (!bytes || bytes.length > 65536) return 2;
    id input = [NSJSONSerialization JSONObjectWithData:bytes options:0 error:nil];
    if (![input isKindOfClass:NSDictionary.class] || ![input[@"cases"] isKindOfClass:NSArray.class]) return 2;
    NSArray* cases = input[@"cases"];
    if (cases.count != 2) return 2;
    unsigned completed = 0;
    for (id entry in cases) {
        if (![entry isKindOfClass:NSDictionary.class]) return 2;
        NSString* name = entry[@"name"];
        if (![name isKindOfClass:NSString.class] ||
            (![name isEqual:@"normal"] && ![name isEqual:@"small"])) return 2;
        if (selected != "pair" && selected != name.UTF8String) continue;
        NSArray* encoded = entry[@"parameter_sets_base64"];
        if (![encoded isKindOfClass:NSArray.class] || encoded.count != 3) return 2;
        NSMutableArray* keep = [NSMutableArray array];
        std::vector<const uint8_t*> pointers;
        std::vector<size_t> lengths;
        for (id value in encoded) {
            if (![value isKindOfClass:NSString.class]) return 2;
            NSData* set = [[NSData alloc] initWithBase64EncodedString:value options:0];
            if (!set || set.length < 2 || set.length > 4096) return 2;
            [keep addObject:set];
            pointers.push_back(static_cast<const uint8_t*>(set.bytes));
            lengths.push_back(set.length);
        }
        CMVideoFormatDescriptionRef format = nullptr;
        OSStatus status = CMVideoFormatDescriptionCreateFromHEVCParameterSets(kCFAllocatorDefault,
            pointers.size(), pointers.data(), lengths.data(), 4, nullptr, &format);
        if (status || !format) {
            emit(@{@"phase":@"format_failed", @"case":name, @"status":@(status)});
            return 4;
        }
        CMVideoDimensions dims = CMVideoFormatDescriptionGetDimensions(format);
        bool expected = [name isEqual:@"normal"] ? dims.width == 1280 && dims.height == 720
                                                : dims.width == 320 && dims.height == 240;
        emit(@{@"phase":@"format_ready", @"case":name, @"width":@(dims.width),
               @"height":@(dims.height), @"dimensions_match":@(expected),
               @"decoder_session_requested":@(hardware || software)});
        if (!expected) { CFRelease(format); return 4; }
        if (hardware || software) {
            // Match Chromium's normal-required/small-permitted policy in hardware mode.
            // The control forbids hardware explicitly, unlike Chromium's small probe.
            NSDictionary* spec = @{
                (__bridge NSString*)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder:@(hardware),
                (__bridge NSString*)kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder:@(hardware && [name isEqual:@"normal"])};
            NSDictionary* attrs = @{
                (__bridge NSString*)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
                (__bridge NSString*)kCVPixelBufferWidthKey:@(dims.width),
                (__bridge NSString*)kCVPixelBufferHeightKey:@(dims.height)};
            VTDecompressionOutputCallbackRecord callback = {};
            VTDecompressionSessionRef session = nullptr;
            emit(@{@"phase":@"before_create", @"case":name, @"frames_submitted":@0,
                   @"hardware_permitted":@(hardware)});
            status = VTDecompressionSessionCreate(kCFAllocatorDefault, format,
                (__bridge CFDictionaryRef)spec, (__bridge CFDictionaryRef)attrs, &callback, &session);
            emit(@{@"phase":@"after_create", @"case":name, @"status":@(status), @"session_created":@(session != nullptr)});
            if (session) {
                CFTypeRef actual = nullptr;
                OSStatus property = VTSessionCopyProperty(session,
                    kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder, kCFAllocatorDefault, &actual);
                bool known = !property && actual && CFGetTypeID(actual) == CFBooleanGetTypeID();
                bool used = known && CFBooleanGetValue(static_cast<CFBooleanRef>(actual));
                emit(@{@"phase":@"selection", @"case":name, @"property_status":@(property),
                       @"hardware_actual":known ? (id)@(used) : (id)NSNull.null});
                if (actual) CFRelease(actual);
                if (invalidate) {
                    emit(@{@"phase":@"before_invalidate", @"case":name});
                    VTDecompressionSessionInvalidate(session);
                    emit(@{@"phase":@"after_invalidate", @"case":name});
                }
                emit(@{@"phase":@"before_release", @"case":name});
                CFRelease(session);
                emit(@{@"phase":@"after_release", @"case":name});
            }
            if (status || !session) { CFRelease(format); return 5; }
        }
        CFRelease(format);
        ++completed;
    }
    if (completed != (selected == "pair" ? 2u : 1u)) return 2;
    emit(@{@"phase":@"complete", @"cases_completed":@(completed), @"frames_submitted":@0,
           @"mode":hardware ? @"hardware-permitted" : software ? @"software-only" : @"format-only",
           @"cleanup":invalidate ? @"explicit-invalidate-then-release" : @"release-only",
           @"scope":@"HEVC subset; excludes earlier H264/VP9 probes and Electron sandbox/process environment"});
    return 0;
} }
