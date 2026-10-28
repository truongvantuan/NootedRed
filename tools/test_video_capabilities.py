"""Execute the production video capability removers; no kext/GPU use."""
from pathlib import Path
import subprocess,tempfile
from test_patch_dispatch import method
ROOT=Path(__file__).resolve().parents[1]
shim=r'''
#include <map>
#include <string>
#include <cassert>
#include <cstdio>
struct OSDictionary{std::map<std::string,int> keys;void removeObject(const char* k){keys.erase(k);}};
'''
cases=r'''
OSDictionary fixture(){OSDictionary p;for(const char* k:{"IOGVACodec","IOGVAHEVCDecode","IOGVAHEVCDecodeCapabilities","IOGVAHEVCEncode","IOGVAHEVCEncodeCapabilities","IOGVAH264EncodeCapabilities","IONameMatch","Unrelated"})p.keys[k]=1;return p;}
int main(){
 stripVideoCapabilities(nullptr);stripHEVCCapabilities(nullptr,false);
 auto all=fixture();stripVideoCapabilities(&all);assert(all.keys.size()==2&&all.keys.count("IONameMatch")&&all.keys.count("Unrelated"));stripVideoCapabilities(&all);assert(all.keys.size()==2);
 auto avc=fixture();stripHEVCCapabilities(&avc,false);assert(avc.keys.size()==4&&avc.keys.count("IOGVACodec")&&avc.keys.count("IOGVAH264EncodeCapabilities"));
 auto encode=fixture();stripHEVCCapabilities(&encode,true);assert(encode.keys.size()==6&&encode.keys.count("IOGVAHEVCEncode")&&encode.keys.count("IOGVAHEVCEncodeCapabilities"));
 puts("video capabilities: NoVDA removes six capabilities, NoHEVC preserves AVC, AVCEncode preserves HEVC encode, unrelated metadata and null/idempotent paths passed");
}
'''
s=(ROOT/'NootedRed/DriverInjector.cpp').read_text()
assert 'stripVideoCapabilities(dict)' in s and 'stripHEVCCapabilities(dict,' in s
with tempfile.TemporaryDirectory(prefix='nred-video-caps-') as d:
 p=Path(d);(p/'test.cpp').write_text(shim+method(s,'void stripVideoCapabilities(')+method(s,'void stripHEVCCapabilities(')+cases)
 subprocess.run(['xcrun','clang++','-std=c++17','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True);subprocess.run([str(p/'test')],check=True)
