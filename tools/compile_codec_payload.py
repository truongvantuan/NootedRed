"""Compile isolated guard assembly and extract __text; no GPU or system mutations."""
from pathlib import Path
import struct,subprocess
WORK=Path('build/codec-payload')
def compile_payload(source,label):
 WORK.mkdir(parents=True,exist_ok=True);asm=WORK/(label+'.s');obj=WORK/(label+'.o');asm.write_text(source)
 subprocess.run(['xcrun','clang','-target','x86_64-apple-macos11.0','-c',str(asm),'-o',str(obj)],check=True,timeout=60)
 data=obj.read_bytes();assert struct.unpack_from('<I',data)[0]==0xfeedfacf
 cursor=32
 for _ in range(struct.unpack_from('<I',data,16)[0]):
  cmd,size=struct.unpack_from('<II',data,cursor);assert size>=8 and cursor+size<=len(data)
  if cmd==0x19:
   for i in range(struct.unpack_from('<I',data,cursor+64)[0]):
    pos=cursor+72+80*i;assert pos+80<=cursor+size
    if data[pos:pos+16].rstrip(b'\0')==b'__text':
     length=struct.unpack_from('<Q',data,pos+40)[0];offset=struct.unpack_from('<I',data,pos+48)[0]
     assert offset+length<=len(data);return data[offset:offset+length]
  cursor+=size
 raise ValueError('No __text in assembled payload')
