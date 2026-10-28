#!/usr/bin/env python3
"""Read-only check of exact 24H232 media pages against embedded cache CodeDirectory hashes.
This checks page integrity, not CMS trust, hardware output or arbitrary future builds.
"""
from pathlib import Path
import hashlib,json,re,struct,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gen_vda_va_data import DyldCache,DEFAULT_CACHE_DIR
base=Path(__file__).resolve().parents[1]/'NootedRed'
results=[]
with DyldCache(DEFAULT_CACHE_DIR) as c:
 for name in ['VDAVADataSequoia24H232.hpp','VDAGVADataSequoia24H232.hpp']:
  text=(base/name).read_text()
  pages={int(n):bytes(int(x,16) for x in re.findall(r'0x([0-9A-Fa-f]{2})',body)) for n,body in re.findall(r'UInt8 Page(\d+)\[4096\] = \{(.*?)\};',text,re.S)}
  if name.startswith('VDAVA'):
   imagebase=int(re.search(r'ImageBase = (0x[0-9A-Fa-f]+)',text)[1],16)
   addresses={int(n):imagebase+int(off,16) for n,off in re.findall(r'// Page (\d+):.*image offset (0x[0-9A-Fa-f]+)',text)}
  else:addresses={0:int(re.search(r'// source page: (0x[0-9A-Fa-f]+)',text)[1],16)}
  assert set(addresses)==set(pages)
  for number,page in pages.items():
   assert len(page)==4096
   addr=addresses[number];start,_,offset,h=c.mapping_for(addr);position=offset+addr-start
   h.seek(position);actual=h.read(4096);assert actual==page,(name,number,'file changed')
   h.seek(40);sigoff,sigsize=struct.unpack('<QQ',h.read(16));h.seek(sigoff);blob=h.read(sigsize)
   assert struct.unpack_from('>I',blob)[0]==0xfade0cc0
   verified=[]
   for i in range(struct.unpack_from('>I',blob,8)[0]):
    _,cdpos=struct.unpack_from('>II',blob,12+8*i)
    if struct.unpack_from('>I',blob,cdpos)[0]!=0xfade0c02:continue
    cd=blob[cdpos:];hashoff,_,_,count,limit=struct.unpack_from('>5I',cd,16);size,typ,_,power=struct.unpack_from('4B',cd,36)
    assert power==12 and position%4096==0 and position+4096<=limit
    slot=position//4096;assert slot<count
    expected=cd[hashoff+slot*size:hashoff+(slot+1)*size];actualhash=hashlib.new({1:'sha1',2:'sha256',3:'sha256',4:'sha384'}[typ],page).digest()[:size]
    assert actualhash==expected,(name,number,'CodeDirectory mismatch')
    verified.append(typ)
   assert verified
   results.append({'header':name,'page':number,'address':hex(addr),'sha256':hashlib.sha256(page).hexdigest(),'CodeDirectory_hash_types':verified})
print(json.dumps(results,indent=2))
print('Verified',len(results),'generated pages against live file and embedded cache CodeDirectory; no page normalization')
