#!/usr/bin/env python3
"""Exercise the production Main10 capability mutator with host dictionary stubs."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from test_patch_dispatch import method
ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''
#include <cassert>
#include <map>
#include <string>
#include <cstdio>
struct OSObject {virtual ~OSObject()=default;};
bool failAllocation=false,failSet=false;int releases=0;
struct OSNumber:OSObject{unsigned long long value=0;unsigned bits=0;
 static OSNumber* withNumber(unsigned long long v,unsigned b){static OSNumber n;if(failAllocation)return nullptr;n.value=v;n.bits=b;return &n;}
 void release(){++releases;}
};
struct OSDictionary:OSObject{std::map<std::string,OSObject*> values;
 OSObject* getObject(const char*k){auto i=values.find(k);return i==values.end()?nullptr:i->second;}
 bool setObject(const char*k,OSObject*v){if(failSet)return false;values[k]=v;return true;}
};
#define OSDynamicCast(type,value) dynamic_cast<type*>(value)
'''
CASES=r'''
int main(){OSDictionary p,caps,details,main,main10,encode;OSNumber old,mainLevel;old.value=153;mainLevel.value=153;
 p.values["IOGVAHEVCDecodeCapabilities"]=&caps;p.values["IOGVAHEVCEncodeCapabilities"]=&encode;
 caps.values["VTPerProfileDetails"]=&details;details.values["1"]=&main;details.values["2"]=&main10;
 main.values["VTMaxDecodeLevel"]=&mainLevel;main10.values["VTMaxDecodeLevel"]=&old;
 assert(capHEVCMain10(&p));auto* zero=dynamic_cast<OSNumber*>(main10.getObject("VTMaxDecodeLevel"));
 assert(zero&&zero->value==0&&zero->bits==32&&releases==1);
 assert(main.getObject("VTMaxDecodeLevel")==&mainLevel&&mainLevel.value==153);
 assert(p.getObject("IOGVAHEVCEncodeCapabilities")==&encode);
 assert(capHEVCMain10(&p)&&releases==2);
 failAllocation=true;main10.values["VTMaxDecodeLevel"]=&old;
 assert(!capHEVCMain10(&p)&&main10.getObject("VTMaxDecodeLevel")==&old);
 failAllocation=false;failSet=true;
 assert(!capHEVCMain10(&p)&&main10.getObject("VTMaxDecodeLevel")==&old&&releases==3);failSet=false;
 assert(!capHEVCMain10(nullptr));OSDictionary empty;assert(!capHEVCMain10(&empty));
 details.values.erase("2");assert(!capHEVCMain10(&p));
 puts("Main10 policy: only Profile 2 capped; Main/encode preserved; allocation/set/missing-data failure passed");
}
'''
def main():
 source=(ROOT/'NootedRed/DriverInjector.cpp').read_text()
 assert 'else if (!VDA::singleton().isHEVC10Allowed())' in source
 with tempfile.TemporaryDirectory(prefix='nred-main10-') as temp:
  path=Path(temp);(path/'test.cpp').write_text(SHIM+method(source,'bool capHEVCMain10(')+CASES)
  subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-fsanitize=address,undefined',str(path/'test.cpp'),'-o',str(path/'test')],check=True)
  subprocess.run([str(path/'test')],check=True)
if __name__=='__main__':main()
