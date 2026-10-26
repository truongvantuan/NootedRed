// Offscreen Metal render/compute pixel readback; launches no application UI.
#import <Foundation/Foundation.h>
#include "user_cache_probe.h"
#import <Metal/Metal.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <unistd.h>

static NSString* shaders = @R"(
#include <metal_stdlib>
using namespace metal;
vertex float4 vertexMain(uint i [[vertex_id]]) {
    const float2 p[] = {float2(-1,-1),float2(3,-1),float2(-1,3)};
    return float4(p[i],0,1);
}
fragment float4 singleMain() { return float4(0.8,0.2,0.4,0.6); }
struct Dual { float4 main [[color(0),index(0)]]; float4 second [[color(0),index(1)]]; };
fragment Dual dualMain() { return {float4(0.8,0.2,0.4,0.6),float4(0.25,0.5,0.75,0.5)}; }
kernel void computeMain(device uint* output [[buffer(0)]], uint i [[thread_position_in_grid]]) {
    if (i<64) output[i]=i*i+7;
}
)";

static bool wait(id<MTLCommandBuffer> command, NSMutableDictionary* report) {
    [command commit]; [command waitUntilCompleted];
    report[@"command_status"] = @(command.status);
    if (command.error) report[@"error"] = command.error.localizedDescription;
    return command.status == MTLCommandBufferStatusCompleted && !command.error;
}
static bool render(id<MTLDevice> device, id<MTLLibrary> library, NSMutableDictionary* report) {
    NSMutableArray* cases = [NSMutableArray array];
    id<MTLCommandQueue> queue = [device newCommandQueue];
    if (!queue) return false;
    bool all = true;
    for (unsigned which=0;which<3;which++) {
        NSMutableDictionary* item = [@{@"case":@[@"opaque",@"source-alpha",@"dual-source-color"][which]} mutableCopy];
        [cases addObject:item];
        MTLRenderPipelineDescriptor* pipeline = [MTLRenderPipelineDescriptor new];
        pipeline.vertexFunction = [library newFunctionWithName:@"vertexMain"];
        pipeline.fragmentFunction = [library newFunctionWithName:which==2?@"dualMain":@"singleMain"];
        auto color = pipeline.colorAttachments[0]; color.pixelFormat = MTLPixelFormatRGBA8Unorm;
        if (which) {
            color.blendingEnabled = YES;
            color.rgbBlendOperation = color.alphaBlendOperation = MTLBlendOperationAdd;
            color.sourceRGBBlendFactor = which==2?MTLBlendFactorSource1Color:MTLBlendFactorSourceAlpha;
            color.destinationRGBBlendFactor = which==2?MTLBlendFactorOneMinusSource1Color:MTLBlendFactorOneMinusSourceAlpha;
            color.sourceAlphaBlendFactor = which==2?MTLBlendFactorSource1Alpha:MTLBlendFactorOne;
            color.destinationAlphaBlendFactor = which==2?MTLBlendFactorOneMinusSource1Alpha:MTLBlendFactorOneMinusSourceAlpha;
        }
        NSError* error = nil;
        id<MTLRenderPipelineState> state = [device newRenderPipelineStateWithDescriptor:pipeline error:&error];
        if (!state) { item[@"passed"]=@NO; item[@"error"]=error.localizedDescription?:@"pipeline creation failed"; all=false; continue; }
        auto description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                                                          width:32 height:32 mipmapped:NO];
        description.usage = MTLTextureUsageRenderTarget;
        description.storageMode = MTLStorageModeManaged;
        id<MTLTexture> texture = [device newTextureWithDescriptor:description];
        id<MTLCommandBuffer> command = [queue commandBuffer];
        if (!texture || !command) { item[@"passed"]=@NO; all=false; continue; }
        auto pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = texture;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0.1,0.3,0.2,0.4);
        auto encoder = [command renderCommandEncoderWithDescriptor:pass];
        if (!encoder) { item[@"passed"]=@NO; all=false; continue; }
        [encoder setRenderPipelineState:state];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [encoder endEncoding];
        auto blit = [command blitCommandEncoder];
        if (!blit) { item[@"passed"]=@NO; all=false; continue; }
        [blit synchronizeResource:texture]; [blit endEncoding];
        if (!wait(command,item)) { item[@"passed"]=@NO; all=false; break; }
        uint8_t pixels[32*32*4];
        [texture getBytes:pixels bytesPerRow:32*4 fromRegion:MTLRegionMake2D(0,0,32,32) mipmapLevel:0];
        const double expected[3][4] = {{0.8,0.2,0.4,0.6},{0.52,0.24,0.32,0.76},{0.275,0.25,0.35,0.5}};
        unsigned maximum=0;
        for (unsigned i=0;i<sizeof(pixels);i++) {
            unsigned difference = std::abs(int(pixels[i])-int(std::lround(expected[which][i%4]*255)));
            maximum = std::max(maximum,difference);
        }
        item[@"first_pixel_rgba8"] = @[@(pixels[0]),@(pixels[1]),@(pixels[2]),@(pixels[3])];
        item[@"max_absolute_channel_error"] = @(maximum);
        item[@"tolerance"] = @2;
        item[@"passed"] = @(maximum<=2);
        all = all && maximum<=2;
    }
    report[@"render_cases"] = cases;
    return all && cases.count==3;
}
static bool compute(id<MTLDevice> device, id<MTLLibrary> library, NSMutableDictionary* report) {
    NSError* error = nil;
    auto state = [device newComputePipelineStateWithFunction:[library newFunctionWithName:@"computeMain"] error:&error];
    if (!state) { report[@"error"]=error.localizedDescription?:@"compute pipeline failed"; return false; }
    auto buffer = [device newBufferWithLength:64*sizeof(uint32_t) options:MTLResourceStorageModeManaged];
    auto queue = [device newCommandQueue]; auto command = [queue commandBuffer];
    if (!buffer || !queue || !command) return false;
    memset(buffer.contents,0,64*sizeof(uint32_t)); [buffer didModifyRange:NSMakeRange(0,64*sizeof(uint32_t))];
    auto encoder = [command computeCommandEncoder];
    if (!encoder) return false;
    [encoder setComputePipelineState:state]; [encoder setBuffer:buffer offset:0 atIndex:0];
    [encoder dispatchThreads:MTLSizeMake(64,1,1) threadsPerThreadgroup:MTLSizeMake(32,1,1)];
    [encoder endEncoding];
    auto blit = [command blitCommandEncoder];
    if (!blit) return false;
    [blit synchronizeResource:buffer]; [blit endEncoding];
    if (!wait(command,report)) return false;
    auto data = static_cast<uint32_t*>(buffer.contents);
    unsigned matches=0; for(unsigned i=0;i<64;i++) matches+=data[i]==i*i+7;
    report[@"matching_elements"]=@(matches); report[@"expected_elements"]=@64;
    return matches==64;
}
int main(int argc,const char* argv[]) {
    @autoreleasepool {
        NSString* mode = argc==2?[NSString stringWithUTF8String:argv[1]]:@"";
        if (![mode isEqualToString:@"--cache-only"] && ![mode isEqualToString:@"--render"] && ![mode isEqualToString:@"--compute"]) {
            fprintf(stderr,"usage: metal_probe --render | --compute\n"); return 2;
        }
        if ([mode isEqualToString:@"--cache-only"]) {
            NSDictionary* snapshot = cacheSnapshot();
            NSDictionary* report = @{@"mode":mode,@"cache_patch_snapshot":snapshot,@"GPU_work_submitted":@NO};
            NSData* data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
            if(data) { fwrite(data.bytes,1,data.length,stdout); fputc('\n',stdout); }
            return [snapshot[@"available"] boolValue] ? 0 : 1;
        }
        alarm(30);
        NSMutableDictionary* report = [@{@"mode":mode,@"passed":@NO} mutableCopy];
        auto device = MTLCreateSystemDefaultDevice();
        if (device) {
            report[@"device_name"]=device.name;
            report[@"registry_id"]=@(device.registryID);
            NSError* error = nil;
            auto library = [device newLibraryWithSource:shaders options:nil error:&error];
            if (!library) report[@"error"]=error.localizedDescription?:@"Metal compilation failed";
            else report[@"passed"]=@([mode isEqualToString:@"--render"]?render(device,library,report):compute(device,library,report));
        } else report[@"error"]=@"No Metal device";
        report[@"cache_patch_snapshot"] = cacheSnapshot();
        auto data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
        if(data) { fwrite(data.bytes,1,data.length,stdout); fputc('\n',stdout); }
        return [report[@"passed"] boolValue]?0:1;
    }
}
