// Native, hardware-required VideoToolbox verification with pixel readback.
// Build: clang++ -std=c++17 -fobjc-arc tools/video_probe.mm -framework Foundation \
//   -framework VideoToolbox -framework CoreVideo -framework CoreMedia -o build/tools/video_probe
// Every hardware mode requests RequireHardwareAccelerated* and verifies UsingHardwareAccelerated*.
#import <Foundation/Foundation.h>
#include "user_cache_probe.h"
#import <VideoToolbox/VideoToolbox.h>
#import <CoreVideo/CoreVideo.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <mutex>
#include <vector>
#include <unistd.h>

constexpr int width = 1280, height = 720, frameCount = 3;
using Pixels = std::vector<uint8_t>;
struct Encoded {
    std::mutex mutex;
    std::vector<CMSampleBufferRef> samples;
    OSStatus error = noErr;
    ~Encoded() { for (auto sample : samples) CFRelease(sample); }
};
struct Decoded {
    std::mutex mutex;
    std::vector<Pixels> frames = std::vector<Pixels>(frameCount);
    OSStatus error = noErr;
    unsigned callbacks = 0;
};

static NSDictionary* videoCacheSnapshot() {
    NSMutableDictionary* report = [cacheSnapshot() mutableCopy];
    if (![report[@"cache_uuid_hex"] isEqualToString:@"42ec2890bc40317ebb2745142bff7f26"]) return report;
    auto getRange = reinterpret_cast<const void*(*)(size_t*)>(dlsym(RTLD_DEFAULT,"_dyld_get_shared_cache_range"));
    size_t size=0;uint64_t base=getRange ? reinterpret_cast<uint64_t>(getRange(&size)) : 0;
    if (!base) return report;
    // Read this process's actual shared-cache mappings. File reads alone can
    // return stock bytes even while another process executes validated pages.
    NSMutableDictionary* pages = [NSMutableDictionary dictionary];
    for (uint64_t offset : {0x308606000ULL,0x308608000ULL,0x30860f000ULL,
                           0x30864c000ULL,0x30864d000ULL,0x30864f000ULL,
                           0x308650000ULL,0x308667000ULL,0x30867d000ULL}) {
        pages[[NSString stringWithFormat:@"0x%llx",static_cast<unsigned long long>(offset)]] = readHex(base+offset,4096);
    }
    report[@"video_pages"] = pages;
    return report;
}

static Pixels pattern(int frame) {
    Pixels p(width * height * 3 / 2);
    for (int y = 0; y < height; y++) for (int x = 0; x < width; x++)
        p[y * width + x] = 32 + ((x / 80 + y / 80 + frame) % 6) * 32;
    for (int y = 0; y < height / 2; y++) for (int x = 0; x < width; x += 2) {
        p[width * height + y * width + x] = 80 + ((x / 160 + frame) % 4) * 24;
        p[width * height + y * width + x + 1] = 80 + ((y / 80 + frame) % 4) * 24;
    }
    return p;
}

static bool pixels(CVPixelBufferRef buffer, Pixels& bytes, bool fill, int frame = 0) {
    if (!buffer || CVPixelBufferGetWidth(buffer) != width || CVPixelBufferGetHeight(buffer) != height
        || CVPixelBufferGetPixelFormatType(buffer) != kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        || CVPixelBufferGetPlaneCount(buffer) != 2) return false;
    CVOptionFlags flags = fill ? 0 : kCVPixelBufferLock_ReadOnly;
    if (CVPixelBufferLockBaseAddress(buffer, flags) != kCVReturnSuccess) return false;
    if (fill) bytes = pattern(frame); else bytes.resize(width * height * 3 / 2);
    size_t offset = 0;
    bool ok = true;
    for (size_t plane = 0; plane < 2; plane++) {
        auto* base = static_cast<uint8_t*>(CVPixelBufferGetBaseAddressOfPlane(buffer, plane));
        size_t rows = plane ? height / 2 : height;
        size_t stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, plane);
        if (!base || stride < width) { ok = false; break; }
        for (size_t y = 0; y < rows; y++) {
            if (fill) memcpy(base + y * stride, bytes.data() + offset, width);
            else memcpy(bytes.data() + offset, base + y * stride, width);
            offset += width;
        }
    }
    if (CVPixelBufferUnlockBaseAddress(buffer, flags) != kCVReturnSuccess) ok = false;
    return ok;
}

static void compressed(void* context, void*, OSStatus status, VTEncodeInfoFlags flags, CMSampleBufferRef sample) {
    auto& out = *static_cast<Encoded*>(context);
    std::lock_guard<std::mutex> lock(out.mutex);
    if (status || !sample || !CMSampleBufferDataIsReady(sample) || (flags & kVTEncodeInfo_FrameDropped)) {
        out.error = status ? status : -1; return;
    }
    CFRetain(sample); out.samples.push_back(sample);
}
static void decompressed(void* context, void* frame, OSStatus status, VTDecodeInfoFlags flags,
                         CVImageBufferRef image, CMTime, CMTime) {
    auto& out = *static_cast<Decoded*>(context);
    std::lock_guard<std::mutex> lock(out.mutex);
    size_t index = reinterpret_cast<uintptr_t>(frame) - 1;
    if (status || !image || index >= frameCount || (flags & kVTDecodeInfo_FrameDropped)
        || !out.frames[index].empty() || !pixels(image, out.frames[index], false)) {
        out.error = status ? status : -1; return;
    }
    ++out.callbacks;
}
static bool hardwareProperty(VTSessionRef session, CFStringRef key, bool expected, OSStatus& status, bool& defaulted,
                             int* observed = nullptr) {
    CFTypeRef value = nullptr;
    status = VTSessionCopyProperty(session, key, kCFAllocatorDefault, &value);
    defaulted = !expected && status == kVTPropertyNotSupportedErr;
    if (observed) {
        *observed = defaulted ? 0 : -1;
        if (!status && value && CFGetTypeID(value)==CFBooleanGetTypeID())
            *observed = CFBooleanGetValue(static_cast<CFBooleanRef>(value)) ? 1 : 0;
    }
    // The SDK documents an unsupported UsingHardware* property as false by default.
    // Accept that default only when software is expected, never in a hardware-required test.
    if (defaulted) { status = noErr; if (value) CFRelease(value); return true; }
    bool valid = !status && value && CFGetTypeID(value) == CFBooleanGetTypeID()
                 && (CFBooleanGetValue(static_cast<CFBooleanRef>(value)) == expected);
    if (value) CFRelease(value);
    if (!valid && !status) status = -2;
    return valid;
}

static bool encode(CMVideoCodecType codec, bool hardware, bool sourcePool, Encoded& out, NSMutableDictionary* report,
                   bool automatic = false) {
    NSDictionary* spec = hardware
        ? @{(__bridge NSString*)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder:@YES}
        : @{(__bridge NSString*)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@(automatic)};
    report[@"encoder_hardware_required"] = @(hardware);
    report[@"encoder_hardware_allowed"] = @(hardware || automatic);
    report[@"encoder_hardware_expected"] = @(hardware);
    NSDictionary* attributes = @{(__bridge NSString*)kCVPixelBufferPixelFormatTypeKey:
                                    @(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)};
    VTCompressionSessionRef session = nullptr;
    OSStatus status = VTCompressionSessionCreate(kCFAllocatorDefault,width,height,codec,
        (__bridge CFDictionaryRef)spec,(__bridge CFDictionaryRef)attributes,nullptr,compressed,&out,&session);
    report[@"encode_create_status"] = @(status);
    if (status || !session) return false;
    NSDictionary* settings = @{(__bridge NSString*)kVTCompressionPropertyKey_AllowFrameReordering:@NO,
        (__bridge NSString*)kVTCompressionPropertyKey_AverageBitRate:@8000000,
        (__bridge NSString*)kVTCompressionPropertyKey_MaxKeyFrameInterval:@1};
    status = VTSessionSetProperties(session,(__bridge CFDictionaryRef)settings);
    if (!status) status = VTCompressionSessionPrepareToEncodeFrames(session);
    report[@"encode_prepare_status"] = @(status);
    bool defaulted = false;
    int actual = -1;
    bool selected = !status && hardwareProperty(session,kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder,
                                                hardware,status,defaulted,&actual);
    report[@"encoder_using_hardware_actual"] = actual < 0 ? (id)[NSNull null] : @(actual==1);
    report[@"encoder_using_hardware_property_defaulted_false"] = @(defaulted);
    report[@"encoder_selection_verified"] = @(selected);
    report[@"source_allocation"] = sourcePool ? @"compression-session-pool" : @"CVPixelBufferCreate";
    NSMutableArray* sources = [NSMutableArray array];
    for (int i = 0; selected && !status && i < frameCount; i++) {
        CVPixelBufferRef buffer = nullptr;
        if (sourcePool) {
            CVPixelBufferPoolRef pool = VTCompressionSessionGetPixelBufferPool(session);
            status = pool ? CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault,pool,&buffer) : -4;
        } else {
            status = CVPixelBufferCreate(kCFAllocatorDefault,width,height,
                kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,(__bridge CFDictionaryRef)@{},&buffer);
        }
        if (!status && buffer) {
            Pixels source, readback;
            if (!pixels(buffer,source,true,i)) status = -3;
            bool intact = !status && pixels(buffer,readback,false) && readback == source;
            if (!intact && !status) status = -5;
            [sources addObject:@{@"frame":@(i),@"CPU_source_readback_matches":@(intact),
                @"IOSurface_backed":@(CVPixelBufferGetIOSurface(buffer)!=nullptr),
                @"luma_stride":@(CVPixelBufferGetBytesPerRowOfPlane(buffer,0)),
                @"chroma_stride":@(CVPixelBufferGetBytesPerRowOfPlane(buffer,1))}];
            if (!status) status = VTCompressionSessionEncodeFrame(session,buffer,CMTimeMake(i,30),CMTimeMake(1,30),
                                                                  nullptr,nullptr,nullptr);
            CFRelease(buffer);
        }
    }
    if (!status && selected) status = VTCompressionSessionCompleteFrames(session,kCMTimeInvalid);
    VTCompressionSessionInvalidate(session); CFRelease(session);
    report[@"encode_status"] = @(status);
    report[@"encode_callback_status"] = @(out.error);
    report[@"encoded_frames"] = @(out.samples.size());
    report[@"source_buffers"] = sources;
    NSMutableArray* timestamps = [NSMutableArray array];
    for (auto sample : out.samples) [timestamps addObject:@(CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample)))];
    report[@"encoded_sample_PTS_seconds"] = timestamps;
    return selected && !status && !out.error && out.samples.size() == frameCount;
}

static bool decode(Encoded& input, bool hardware, Decoded& output, NSMutableDictionary* report, NSString* prefix,
                   bool automatic = false) {
    if (input.samples.size() != frameCount) return false;
    NSDictionary* spec = hardware
        ? @{(__bridge NSString*)kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder:@YES}
        : @{(__bridge NSString*)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder:@(automatic)};
    report[[prefix stringByAppendingString:@"_hardware_required"]] = @(hardware);
    report[[prefix stringByAppendingString:@"_hardware_allowed"]] = @(hardware || automatic);
    report[[prefix stringByAppendingString:@"_hardware_expected"]] = @(hardware);
    NSDictionary* attrs = @{(__bridge NSString*)kCVPixelBufferPixelFormatTypeKey:
                                @(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)};
    VTDecompressionOutputCallbackRecord callback{decompressed,&output};
    VTDecompressionSessionRef session = nullptr;
    OSStatus status = VTDecompressionSessionCreate(kCFAllocatorDefault,CMSampleBufferGetFormatDescription(input.samples[0]),
        (__bridge CFDictionaryRef)spec,(__bridge CFDictionaryRef)attrs,&callback,&session);
    report[[prefix stringByAppendingString:@"_create_status"]] = @(status);
    if (status || !session) return false;
    bool defaulted = false;
    int actual = -1;
    bool selected = hardwareProperty(session,kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder,hardware,status,defaulted,&actual);
    report[[prefix stringByAppendingString:@"_using_hardware_actual"]] = actual < 0 ? (id)[NSNull null] : @(actual==1);
    report[[prefix stringByAppendingString:@"_using_hardware_property_defaulted_false"]] = @(defaulted);
    report[[prefix stringByAppendingString:@"_selection_verified"]] = @(selected);
    for (int i = 0; selected && !status && i < frameCount; i++) {
        status = VTDecompressionSessionDecodeFrame(session,input.samples[i],kVTDecodeFrame_EnableAsynchronousDecompression,
                                                   reinterpret_cast<void*>(static_cast<uintptr_t>(i+1)),nullptr);
    }
    if (!status && selected) status = VTDecompressionSessionFinishDelayedFrames(session);
    OSStatus waited = VTDecompressionSessionWaitForAsynchronousFrames(session);
    if (!status) status = waited;
    VTDecompressionSessionInvalidate(session); CFRelease(session);
    report[[prefix stringByAppendingString:@"_status"]] = @(status);
    report[[prefix stringByAppendingString:@"_callback_status"]] = @(output.error);
    report[[prefix stringByAppendingString:@"_frames"]] = @(output.callbacks);
    return selected && !status && !output.error && output.callbacks == frameCount;
}

static bool compare(const std::vector<Pixels>& first, const std::vector<Pixels>& second,
                    NSMutableDictionary* report, double threshold, int maxThreshold) {
    uint64_t difference = 0, count = 0; int maximum = 0;
    NSMutableArray* frames = [NSMutableArray array];
    if (first.size() != frameCount || second.size() != frameCount) return false;
    for (size_t i = 0; i < first.size(); i++) {
        if (first[i].size() != width*height*3/2 || first[i].size() != second[i].size()) return false;
        NSMutableArray* planes = [NSMutableArray array];
        for (size_t plane=0;plane<2;plane++) {
            size_t begin=plane ? width*height : 0, end=plane ? first[i].size() : width*height;
            uint64_t error=0,total=0; int low=255,high=0;
            for (size_t j=begin;j<end;j++) {
                error += std::abs(int(first[i][j])-int(second[i][j]));
                total += first[i][j];low=std::min(low,int(first[i][j]));high=std::max(high,int(first[i][j]));
            }
            NSMutableString* grid=[NSMutableString stringWithCapacity:32*18*2];
            size_t rows=plane ? height/2 : height;
            for(size_t y=0;y<18;y++)for(size_t x=0;x<32;x++)
                [grid appendFormat:@"%02x",first[i][begin+(y*rows/18)*width+x*width/32]];
            [planes addObject:@{@"plane":@(plane),@"observed_min":@(low),@"observed_max":@(high),
                @"observed_mean":@(double(total)/(end-begin)),@"mean_absolute_error":@(double(error)/(end-begin)),
                @"sampled_grid_hex":grid,@"grid_columns":@32,@"grid_rows":@18}];
        }
        [frames addObject:@{@"frame":@(i),@"planes":planes}];
        for (size_t j = 0; j < first[i].size(); j++) {
            int d = std::abs(int(first[i][j])-int(second[i][j]));
            difference += d; maximum = std::max(maximum,d); ++count;
        }
    }
    double mean = count ? double(difference)/count : INFINITY;
    report[@"pixel_mean_absolute_error"] = @(mean);
    report[@"pixel_max_absolute_error"] = @(maximum);
    report[@"pixel_mean_error_limit"] = @(threshold);
    report[@"pixel_max_error_limit"] = @(maxThreshold);
    bool ok = mean <= threshold && maximum <= maxThreshold;
    report[@"pixels_within_tolerance"] = @(ok);
    report[@"frame_pixel_statistics"] = frames;
    return ok;
}
int main(int argc, const char* argv[]) {
    @autoreleasepool {
        bool sourcePool = argc == 3 && !strcmp(argv[2],"--source-pool");
        NSString* mode = argc == 2 || sourcePool ? [NSString stringWithUTF8String:argv[1]] : @"";
        NSArray* modes = @[@"--cache-only",@"--software-selftest",@"--software-selftest-hevc",@"--decode-h264",@"--decode-hevc",@"--encode-h264",@"--encode-hevc",@"--decode-hevc-fallback",@"--encode-hevc-fallback"];
        if (![modes containsObject:mode]) {
            fprintf(stderr,"usage: video_probe --software-selftest | --software-selftest-hevc | --decode-h264 | --decode-hevc | --encode-h264 | --encode-hevc | --decode-hevc-fallback | --encode-hevc-fallback [--source-pool]\n");
            return 2;
        }
        if ([mode isEqualToString:@"--cache-only"]) {
            NSDictionary* snapshot = videoCacheSnapshot();
            NSDictionary* report = @{@"mode":mode,@"cache_patch_snapshot":snapshot,@"GPU_work_submitted":@NO};
            NSData* data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
            if(data) { fwrite(data.bytes,1,data.length,stdout); fputc('\n',stdout); }
            return [snapshot[@"available"] boolValue] ? 0 : 1;
        }
        alarm(60);
        bool software = [mode hasPrefix:@"--software-selftest"];
        bool encodeTest = [mode hasPrefix:@"--encode-"];
        bool hevc = [mode containsString:@"hevc"];
        bool fallback = [mode hasSuffix:@"-fallback"];
        NSMutableDictionary* report = [@{@"mode":mode,@"width":@(width),@"height":@(height),
            @"requested_frames":@(frameCount),@"hardware_required":@(!software && !fallback),
            @"automatic_software_fallback_expected":@(fallback)} mutableCopy];
        Encoded encoded; Decoded decoded, reference;
        bool passed = encode(hevc?kCMVideoCodecType_HEVC:kCMVideoCodecType_H264,encodeTest && !fallback,sourcePool,
                             encoded,report,fallback && encodeTest);
        if (passed) passed = decode(encoded,false,reference,report,@"software_decode");
        if (passed && !encodeTest && !software) {
            passed = decode(encoded,!fallback,decoded,report,fallback ? @"automatic_decode" : @"hardware_decode",fallback);
            if (passed) passed = compare(decoded.frames,reference.frames,report,0.5,2);
        } else if (passed) {
            std::vector<Pixels> original; for (int i=0;i<frameCount;i++) original.push_back(pattern(i));
            passed = compare(reference.frames,original,report,8.0,64);
        }
        report[@"passed"] = @(passed);
        report[@"cache_patch_snapshot"] = videoCacheSnapshot();
        NSData* data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
        if (data) { fwrite(data.bytes,1,data.length,stdout); fputc('\n',stdout); }
        return passed ? 0 : 1;
    }
}
