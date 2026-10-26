#!/usr/bin/env python3
"""Check NotificationCenter code-page bytes against its embedded CodeDirectory (no execution)."""
import hashlib
import json
import mmap
from pathlib import Path
import struct
import sys

path=Path('/System/Library/CoreServices/NotificationCenter.app/Contents/MacOS/NotificationCenter')
with path.open('rb') as handle:
    with mmap.mmap(handle.fileno(),0,flags=mmap.MAP_PRIVATE,prot=mmap.PROT_READ|mmap.PROT_EXEC) as mapped:
        data=mapped[:]
base=0
if struct.unpack_from('>I',data)[0]==0xCAFEBABE:
    for i in range(struct.unpack_from('>I',data,4)[0]):
        cpu,_,offset,_,_=struct.unpack_from('>5I',data,8+20*i)
        if cpu==0x01000007:base=offset;break
macho=data[base:]
assert struct.unpack_from('<I',macho)[0]==0xFEEDFACF
position=32;signature=None
for _ in range(struct.unpack_from('<I',macho,16)[0]):
    cmd,size=struct.unpack_from('<II',macho,position)
    assert size>=8 and position+size<=len(macho)
    if cmd==0x1d:
        offset,length=struct.unpack_from('<II',macho,position+8);signature=macho[offset:offset+length]
    position+=size
assert signature is not None and struct.unpack_from('>I',signature)[0]==0xfade0cc0
results=[]
for i in range(struct.unpack_from('>I',signature,8)[0]):
    slot,offset=struct.unpack_from('>II',signature,12+8*i)
    if struct.unpack_from('>I',signature,offset)[0]!=0xfade0c02:continue
    directory=signature[offset:]
    hash_offset,_,_,count,limit=struct.unpack_from('>5I',directory,16)
    hash_size,hash_type,_,power=struct.unpack_from('4B',directory,36)
    algorithm={1:'sha1',2:'sha256',3:'sha256',4:'sha384'}[hash_type];page_size=1<<power
    assert count>0 and count*page_size>=limit and hash_offset+count*hash_size<=len(directory)
    mismatch=[]
    for index in range(count):
        start=index*page_size;page=macho[start:min(start+page_size,limit)]
        expected=directory[hash_offset+index*hash_size:hash_offset+(index+1)*hash_size]
        if hashlib.new(algorithm,page).digest()[:hash_size]!=expected:mismatch.append(hex(start))
    results.append({'slot':slot,'hash_type':hash_type,'code_pages_checked':count,'mismatching_pages':mismatch})
passed=bool(results) and all(not x['mismatching_pages'] for x in results)
print(json.dumps({'path':str(path),'method':'Read-only executable file mapping; no application code executed',
                  'all_code_pages_match':passed,'results':results},indent=2))
sys.exit(0 if passed else 1)
