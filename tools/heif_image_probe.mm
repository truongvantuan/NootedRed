// Explicit one-image HEIF diagnostic. Inspection is the default; no ImageIO decode without --decode.
#import <Foundation/Foundation.h>
#import <ImageIO/ImageIO.h>
#import <CoreGraphics/CoreGraphics.h>
#include <CommonCrypto/CommonDigest.h>
#include <sys/sysctl.h>
#include <vector>
#include <string>
#include <cstdio>
static void emit(NSDictionary* d) {
 NSData* b=[NSJSONSerialization dataWithJSONObject:d options:NSJSONWritingPrettyPrinted error:nil];
 fwrite(b.bytes,1,b.length,stdout);fputc('\n',stdout);fflush(stdout);
}
int main(int argc,char** argv) {@autoreleasepool {
 if(argc<2){fprintf(stderr,"usage: heif_image_probe image.heic [--decode] [--hardware-test --yes] [--imageio-software]\n");return 2;}
 bool decode=false,hardwareTest=false,yes=false,imageioSoftware=false;
 for(int i=2;i<argc;++i){std::string a(argv[i]);if(a=="--decode")decode=true;else if(a=="--hardware-test")hardwareTest=true;else if(a=="--yes")yes=true;else if(a=="--imageio-software")imageioSoftware=true;else return 2;}
 // Metadata-only mode avoids ImageIO entirely. inspect_heif.py supplies the complete offline item metadata.
 NSData* source=[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
 if(!source||source.length>32*1024*1024)return 2;
 unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256(source.bytes,(CC_LONG)source.length,digest);
 NSMutableString* inputHash=[NSMutableString string];for(unsigned char v:digest)[inputHash appendFormat:@"%02x",v];
 size_t n=0;if(sysctlbyname("kern.bootargs",nullptr,&n,nullptr,0)||n>65536)return 2;
 std::vector<char> bytes(n+1);if(sysctlbyname("kern.bootargs",bytes.data(),&n,nullptr,0))return 2;
 std::string args=" "+std::string(bytes.data())+" ";auto has=[&](const char* flag){return args.find(std::string(" ")+flag+" ")!=std::string::npos;};
 bool full=has("-NRedVDA")&&!has("-NRedAVC")&&!has("-NRedAVCEncode");
 bool mitigated=has("-NRedAVCEncode")&&!has("-NRedVDA")&&!has("-NRedAVC");
 emit(@{@"phase":@"input",@"sha256":inputHash,@"bytes":@(source.length),@"decode_requested":@(decode),@"hardware_test":@(hardwareTest),@"full_VDA_boot":@(full),@"mitigated_boot":@(mitigated),@"ImageIO_software_policy_requested":@(imageioSoftware)});
 if(!decode)return 0;
 if(hardwareTest ? (!yes||!full) : !mitigated){emit(@{@"phase":@"refused",@"reason":@"Baseline decode requires AVCEncode mitigation; hardware experiment requires full VDA, --hardware-test and --yes"});return 3;}
 // Flush the exact input identity before touching the decoder. This experiment decodes exactly one image.
 emit(@{@"phase":@"before_ImageIO",@"warning":hardwareTest?@"GPU reset/system freeze is possible; this cannot be contained by a child-process timeout":@"HEVC hardware decode is not advertised on this boot; actual decoder backend is not traced"});
 // This private ImageIO option was identified in this machine's native HEIFReadPlugin.
 // It is a diagnostic request, not a claim that the decoder honored the policy.
 NSMutableDictionary* opts=[@{(__bridge NSString*)kCGImageSourceShouldCache:@NO} mutableCopy];
 if(imageioSoftware)opts[@"kCGImageSourceUseHardwareAcceleration"]=@NO;
 CGImageSourceRef src=CGImageSourceCreateWithData((__bridge CFDataRef)source,(__bridge CFDictionaryRef)opts);if(!src){emit(@{@"phase":@"failed",@"reason":@"source creation"});return 4;}
 CFDictionaryRef properties=CGImageSourceCopyPropertiesAtIndex(src,0,nullptr);
 NSDictionary* propertiesObj=(__bridge NSDictionary*)properties;
 size_t pw=[propertiesObj[(__bridge NSString*)kCGImagePropertyPixelWidth] unsignedLongLongValue];
 size_t ph=[propertiesObj[(__bridge NSString*)kCGImagePropertyPixelHeight] unsignedLongLongValue];
 if(properties)CFRelease(properties);
 if(!pw||!ph||pw>4096||ph>4096){CFRelease(src);emit(@{@"phase":@"refused",@"reason":@"missing or excessive metadata dimensions"});return 6;}
 NSMutableDictionary* decodeOpts=[opts mutableCopy];decodeOpts[(__bridge NSString*)kCGImageSourceShouldCacheImmediately]=@YES;
 CGImageRef image=CGImageSourceCreateImageAtIndex(src,0,(__bridge CFDictionaryRef)decodeOpts);
 if(!image){CFRelease(src);emit(@{@"phase":@"failed",@"reason":@"image creation"});return 5;}
 size_t w=CGImageGetWidth(image),h=CGImageGetHeight(image);
 if(!w||!h||w>4096||h>4096){CGImageRelease(image);CFRelease(src);return 6;}
 std::vector<unsigned char> rgba(w*h*4);CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();
 CGContextRef ctx=CGBitmapContextCreate(rgba.data(),w,h,8,w*4,cs,kCGImageAlphaPremultipliedLast|kCGBitmapByteOrder32Big);
 if(!ctx){CGColorSpaceRelease(cs);CGImageRelease(image);CFRelease(src);return 7;}
 CGContextDrawImage(ctx,CGRectMake(0,0,w,h),image);
 CC_SHA256(rgba.data(),(CC_LONG)rgba.size(),digest);NSMutableString* outputHash=[NSMutableString string];for(unsigned char v:digest)[outputHash appendFormat:@"%02x",v];
 unsigned lo=255,hi=0;for(size_t i=3;i<rgba.size();i+=4){lo=std::min(lo,(unsigned)rgba[i]);hi=std::max(hi,(unsigned)rgba[i]);}
 CGContextRelease(ctx);CGColorSpaceRelease(cs);CGImageRelease(image);CFRelease(src);
 emit(@{@"phase":@"complete",@"width":@(w),@"height":@(h),@"rgba_sha256":outputHash,@"alpha_min":@(lo),@"alpha_max":@(hi),@"actual_decoder_backend_verified":@NO});return 0;
}}
