#!/usr/bin/env python3
"""Synthetic metadata and bounds checks; no image decoder or GPU use."""
import struct
from inspect_heif import boxes,hvcc,inspect,InvalidHEIF
from isolate_heif_item import isolate

def box(kind,payload):return struct.pack('>I4s',len(payload)+8,kind)+payload

def config(profile,chroma):
 p=bytearray(23);p[0]=1;p[1]=profile;p[12]=30;p[16]=chroma;p[21]=3;return bytes(p)

def fixture():
 infe=lambda i:box(b'infe',bytes([2,0,0,0])+struct.pack('>HH4s',i,0,b'hvc1')+b'\0')
 props=box(b'hvcC',config(1,1))+box(b'hvcC',config(4,0))+box(b'auxC',b'\0'*4+b'urn:mpeg:hevc:2015:auxid:1\0')+box(b'ispe',b'\0'*4+struct.pack('>II',80,80))
 assoc=b'\0'*4+struct.pack('>I',2)+struct.pack('>HB2B',1,2,1,4)+struct.pack('>HB3B',2,3,2,3,4)
 meta=box(b'pitm',b'\0'*4+struct.pack('>H',1))+box(b'iinf',b'\0'*4+struct.pack('>H',2)+infe(1)+infe(2))+box(b'iprp',box(b'ipco',props)+box(b'ipma',assoc))+box(b'iref',b'\0'*4+box(b'auxl',struct.pack('>HHH',2,1,1)))
 return box(b'ftyp',b'heic'+b'\0'*4+b'mif1')+box(b'meta',b'\0'*4+meta)

def rejects(f):
 try:f()
 except InvalidHEIF:return
 raise AssertionError('malformed metadata accepted')

def main():
 b=fixture();d=inspect(b);assert d['primary_item']==1 and d['items'][2]['properties'][0]['profile_idc']==4
 assert d['items'][2]['properties'][1]['auxiliary_type'].endswith('auxid:1')
 assert d['references']==[{'type':'auxl','from':2,'to':[1]}]
 for item in (1,2):
  variant,edits=isolate(b,item);v=inspect(variant)
  assert len(variant)==len(b) and edits and v['primary_item']==item and not v['references']
  assert not any(p['type']=='auxC' for p in v['items'][2]['properties'])
  assert [p for p in v['properties'] if p['type']=='hvcC']==[p for p in d['properties'] if p['type']=='hvcC']
 rejects(lambda:isolate(b,3))
 count=0
 for i in range(len(b)):
  rejects(lambda i=i:inspect(b[:i]));count+=1
 for length in range(23):rejects(lambda length=length:hvcc(config(1,1)[:length]));count+=1
 rejects(lambda:list(boxes(b'\0\0\0\x07free')))
 rejects(lambda:list(boxes(struct.pack('>I4s',0xffffffff,b'free'))))
 rejects(lambda:list(boxes(struct.pack('>I4sQ',1,b'free',0xffffffffffffffff))))
 assert list(boxes(struct.pack('>I4s',0,b'free')))[0][2]==8
 print(f'HEIF metadata: Main/alpha association and {count+3} malformed/truncated/bounds cases passed')
if __name__=='__main__':main()
