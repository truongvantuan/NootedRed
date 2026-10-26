// One compressed HEIF item through ordinary VideoToolbox, separate from ImageIO tile decoding.
// Hardware mode is deliberately explicit and can still freeze the entire machine.
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <CommonCrypto/CommonDigest.h>
#include <sys/sysctl.h>
#include <vector>
#include <string>

static void emit(NSDictionary* d) {
    NSData* bytes=[NSJSONSerialization dataWithJSONObject:d options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(bytes.bytes,1,bytes.length,stdout);fputc('\n',stdout);fflush(stdout);
}
static NSString* hash(NSData* data) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256(data.bytes,(CC_LONG)data.length,digest);
    NSMutableString* s=[NSMutableString string];for(auto v:digest)[s appendFormat:@"%02x",v];return s;
}
struct Output { OSStatus status=0; unsigned count=0; CVPixelBufferRef image=nullptr; };
static void decoded(void* ref,void*,OSStatus status,VTDecodeInfoFlags,CVImageBufferRef image,CMTime,CMTime) {
    auto* out=static_cast<Output*>(ref);out->status=status;out->count++;
    if(image&&!out->image)out->image=CVPixelBufferRetain(image);
}
int main(int argc,char** argv) {@autoreleasepool {
    if(argc<3){fprintf(stderr,"usage: hevc_item_probe item.json --software | --hardware --yes\n");return 2;}
    bool hardware=std::string(argv[2])=="--hardware";
    if(!hardware&&std::string(argv[2])!="--software")return 2;
    if(argc!=(hardware?4:3)||(hardware&&std::string(argv[3])!="--yes"))return 2;
    size_t size=0;if(sysctlbyname("kern.bootargs",nullptr,&size,nullptr,0)||size>65536)return 2;
    std::vector<char> args(size+1);if(sysctlbyname("kern.bootargs",args.data(),&size,nullptr,0))return 2;
    std::string boot=" "+std::string(args.data())+" ";
    auto has=[&](const char* arg){return boot.find(std::string(" ")+arg+" ")!=std::string::npos;};
    if(hardware&&(!has("-NRedVDA")||has("-NRedAVC")||has("-NRedAVCEncode"))){
        emit(@{@"phase":@"refused",@"reason":@"Hardware experiment requires an explicitly prepared full-VDA boot"});return 3;
    }
    NSData* json=[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
    if(!json||json.length>48*1024*1024)return 2;
    NSDictionary* input=[NSJSONSerialization JSONObjectWithData:json options:0 error:nil];
    if(![input isKindOfClass:NSDictionary.class]||[input[@"schema"] intValue]!=1)return 2;
    NSData* sample=[[NSData alloc] initWithBase64EncodedString:input[@"sample_base64"] options:0];
    if(!sample||!sample.length||sample.length>32*1024*1024||![hash(sample) isEqual:input[@"sample_sha256"]])return 2;
    NSArray* encoded=input[@"parameter_sets_base64"];
    if(![encoded isKindOfClass:NSArray.class]||encoded.count<3||encoded.count>64)return 2;
    NSMutableArray* sets=[NSMutableArray array];std::vector<const uint8_t*> pointers;std::vector<size_t> lengths;
    for(NSString* value in encoded){
        NSData* data=[[NSData alloc] initWithBase64EncodedString:value options:0];
        if(!data||data.length<2||data.length>65536)return 2;
        [sets addObject:data];pointers.push_back(static_cast<const uint8_t*>(data.bytes));lengths.push_back(data.length);
    }
    int nalLength=[input[@"configuration"][@"nal_length_bytes"] intValue];if(nalLength<1||nalLength>4)return 2;
    emit(@{@"phase":@"input",@"source_sha256":input[@"source_sha256"],@"item":input[@"item"],
           @"sample_sha256":hash(sample),@"hardware_required":@(hardware),@"configuration":input[@"configuration"]});
    CMVideoFormatDescriptionRef format=nullptr;
    OSStatus status=CMVideoFormatDescriptionCreateFromHEVCParameterSets(kCFAllocatorDefault,pointers.size(),
        pointers.data(),lengths.data(),nalLength,nullptr,&format);
    if(status||!format){emit(@{@"phase":@"format_failed",@"status":@(status)});return 4;}
    CMVideoDimensions dims=CMVideoFormatDescriptionGetDimensions(format);
    if(dims.width<=0||dims.height<=0||dims.width>4096||dims.height>4096){CFRelease(format);return 4;}
    NSDictionary* spec=hardware?@{(__bridge NSString*)kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder:@YES}
        :@{(__bridge NSString*)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder:@NO};
    NSDictionary* attrs=@{(__bridge NSString*)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)};
    Output output;VTDecompressionOutputCallbackRecord callback{decoded,&output};VTDecompressionSessionRef session=nullptr;
    status=VTDecompressionSessionCreate(kCFAllocatorDefault,format,(__bridge CFDictionaryRef)spec,
        (__bridge CFDictionaryRef)attrs,&callback,&session);
    if(status||!session){CFRelease(format);emit(@{@"phase":@"session_failed",@"status":@(status),@"GPU_work_submitted":@NO});return 5;}
    CFTypeRef actual=nullptr;OSStatus property=VTSessionCopyProperty(session,
        kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder,kCFAllocatorDefault,&actual);
    bool known=!property&&actual&&CFGetTypeID(actual)==CFBooleanGetTypeID();
    bool selected=known&&CFBooleanGetValue(static_cast<CFBooleanRef>(actual));
    // Apple's header defines this property as assumed false by default. Accept
    // that default only when hardware was explicitly forbidden in the spec.
    bool softwareDefault=!hardware&&property==kVTPropertyNotSupportedErr;
    bool verified=(known&&selected==hardware)||softwareDefault;
    if(actual)CFRelease(actual);
    emit(@{@"phase":@"decoder_selected",@"hardware_actual":known?(id)@(selected):(id)NSNull.null,
           @"property_status":@(property),@"property_defaulted_false":@(softwareDefault),
           @"selection_verified":@(verified),@"width":@(dims.width),@"height":@(dims.height)});
    if(!verified){VTDecompressionSessionInvalidate(session);CFRelease(session);CFRelease(format);return 6;}
    CMBlockBufferRef block=nullptr;CMSampleBufferRef buffer=nullptr;
    status=CMBlockBufferCreateWithMemoryBlock(kCFAllocatorDefault,nullptr,sample.length,kCFAllocatorDefault,nullptr,0,sample.length,0,&block);
    if(!status)status=CMBlockBufferReplaceDataBytes(sample.bytes,block,0,sample.length);
    size_t sampleSize=sample.length;CMSampleTimingInfo timing{CMTimeMake(1,1),kCMTimeZero,kCMTimeInvalid};
    if(!status)status=CMSampleBufferCreateReady(kCFAllocatorDefault,block,format,1,1,&timing,1,&sampleSize,&buffer);
    if(!status){
        emit(@{@"phase":@"before_submit",@"hardware_actual":@(selected),@"warning":hardware?@"GPU reset or system freeze is possible":@"Software decoder selection verified"});
        status=VTDecompressionSessionDecodeFrame(session,buffer,kVTDecodeFrame_EnableAsynchronousDecompression,nullptr,nullptr);
        if(!status)status=VTDecompressionSessionFinishDelayedFrames(session);
        OSStatus waited=VTDecompressionSessionWaitForAsynchronousFrames(session);if(!status)status=waited;
    }
    VTDecompressionSessionInvalidate(session);CFRelease(session);CFRelease(format);
    if(buffer)CFRelease(buffer);if(block)CFRelease(block);
    NSMutableDictionary* report=[@{@"phase":@"complete",@"status":@(status),@"callback_status":@(output.status),@"frames":@(output.count),
        @"passed":@(!status&&!output.status&&output.count==1&&output.image)} mutableCopy];
    if(output.image){
        report[@"pixel_format"]=@(CVPixelBufferGetPixelFormatType(output.image));
        report[@"width"]=@(CVPixelBufferGetWidth(output.image));report[@"height"]=@(CVPixelBufferGetHeight(output.image));
        CVReturn locked=CVPixelBufferLockBaseAddress(output.image,kCVPixelBufferLock_ReadOnly);
        if(!locked&&CVPixelBufferGetPixelFormatType(output.image)==kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange){
            NSMutableArray* planes=[NSMutableArray array];
            for(size_t p=0;p<CVPixelBufferGetPlaneCount(output.image);p++){
                size_t w=CVPixelBufferGetWidthOfPlane(output.image,p)*(p?2:1),h=CVPixelBufferGetHeightOfPlane(output.image,p);
                size_t stride=CVPixelBufferGetBytesPerRowOfPlane(output.image,p);auto* data=(const uint8_t*)CVPixelBufferGetBaseAddressOfPlane(output.image,p);
                NSMutableData* packed=[NSMutableData dataWithCapacity:w*h];
                if(data&&w<=stride)for(size_t y=0;y<h;y++)[packed appendBytes:data+y*stride length:w];
                [planes addObject:@{@"plane":@(p),@"row_bytes_hashed":@(w),@"rows":@(h),@"sha256":hash(packed)}];
            }
            report[@"planes"]=planes;
        }
        if(!locked)CVPixelBufferUnlockBaseAddress(output.image,kCVPixelBufferLock_ReadOnly);
        CVPixelBufferRelease(output.image);
    }
    emit(report);return [report[@"passed"] boolValue]?0:7;
}}
