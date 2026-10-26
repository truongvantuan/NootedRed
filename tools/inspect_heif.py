#!/usr/bin/env python3
"""Inspect HEIF item/codec metadata without ImageIO, decoding, or GPU submission."""
import argparse,json,struct
from pathlib import Path

class InvalidHEIF(ValueError):pass

def require(ok,message):
    if not ok:raise InvalidHEIF(message)

def boxes(data,start=0,end=None):
    end=len(data) if end is None else end
    require(0<=start<=end<=len(data),'box container bounds')
    count=0
    while start<end:
        require(end-start>=8,'truncated box header')
        size,kind=struct.unpack_from('>I4s',data,start);header=8
        if size==1:
            require(end-start>=16,'truncated extended box header')
            size=struct.unpack_from('>Q',data,start+8)[0];header=16
        elif size==0:size=end-start
        require(header<=size<=end-start,'invalid box size')
        yield kind,start+header,start+size,start
        start+=size;count+=1
        require(count<=10000,'too many boxes')

def hvcc(payload):
    require(len(payload)>=23 and payload[0]==1,'invalid hvcC header')
    pos=23;arrays=[]
    for _ in range(payload[22]):
        require(pos+3<=len(payload),'truncated hvcC array')
        kind=payload[pos]&63;n=struct.unpack_from('>H',payload,pos+1)[0];pos+=3
        for _ in range(n):
            require(pos+2<=len(payload),'truncated NAL length')
            size=struct.unpack_from('>H',payload,pos)[0];pos+=2
            require(size>=2 and pos+size<=len(payload),'invalid NAL size')
            require(((payload[pos]>>1)&63)==kind,'NAL array/type mismatch')
            arrays.append({'type':kind,'bytes':size});pos+=size
    require(pos==len(payload),'unexpected hvcC trailing bytes')
    return {'profile_idc':payload[1]&31,'profile_compatibility':payload[2:6].hex(),
            'tier':(payload[1]>>5)&1,'level_idc':payload[12],
            'chroma_format':payload[16]&3,'bit_depth_luma':8+(payload[17]&7),
            'bit_depth_chroma':8+(payload[18]&7),'nal_length_bytes':(payload[21]&3)+1,'parameter_sets':arrays}

def inspect(data):
    result={'brands':[],'primary_item':None,'items':{},'properties':[],'associations':{},'references':[]}
    top=list(boxes(data));ftyp=[b for b in top if b[0]==b'ftyp'];require(len(ftyp)==1,'missing or multiple ftyp')
    _,a,b,_=ftyp[0];require(b-a>=8 and (b-a)%4==0,'invalid ftyp')
    result['brands']=[data[a:a+4].decode('ascii','replace')]+[data[i:i+4].decode('ascii','replace') for i in range(a+8,b,4)]
    meta=[x for x in top if x[0]==b'meta'];require(len(meta)==1,'missing or multiple meta');_,a,b,_=meta[0];require(b-a>=4,'truncated meta')
    for kind,a,b,offset in boxes(data,a+4,b):
        p=data[a:b]
        if kind==b'pitm':
            require(len(p)>=6,'truncated primary item');fmt='>I' if p[0] else '>H';require(len(p)>=4+struct.calcsize(fmt),'truncated primary ID');result['primary_item']=struct.unpack_from(fmt,p,4)[0]
        elif kind==b'iinf':
            require(len(p)>=6,'truncated iinf');prefix=8 if p[0] else 6
            require(len(p)>=prefix,'truncated item count');declared=int.from_bytes(p[4:prefix],'big');items=list(boxes(data,a+prefix,b));require(len(items)==declared,'item count mismatch')
            for typ,x,y,_ in items:
                require(typ==b'infe','unexpected item entry');v=data[x:y];require(len(v)>=12,'truncated item info')
                version=v[0];require(version in (2,3),'unsupported infe version');width=4 if version==3 else 2;require(len(v)>=4+width+6,'truncated item info')
                item=int.from_bytes(v[4:4+width],'big');itype=v[6+width:10+width].decode('ascii','replace');result['items'][item]={'type':itype,'name':v[10+width:].split(b'\0')[0].decode('utf8','replace')}
        elif kind==b'iref':
            require(len(p)>=4,'truncated iref');width=4 if p[0] else 2
            for typ,x,y,_ in boxes(data,a+4,b):
                q=data[x:y];require(len(q)>=width+2,'truncated reference');origin=int.from_bytes(q[:width],'big');count=int.from_bytes(q[width:width+2],'big');require(len(q)==width+2+count*width,'reference count mismatch')
                result['references'].append({'type':typ.decode('ascii','replace'),'from':origin,'to':[int.from_bytes(q[i:i+width],'big') for i in range(width+2,len(q),width)]})
        elif kind==b'iprp':
            for typ,x,y,_ in boxes(data,a,b):
                if typ==b'ipco':
                    for prop,u,v,off in boxes(data,x,y):
                        val={'index':len(result['properties'])+1,'type':prop.decode('ascii','replace'),'file_offset':off}
                        if prop==b'hvcC':val.update(hvcc(data[u:v]))
                        elif prop==b'ispe':
                            require(v-u==12,'invalid ispe');val.update(zip(('width','height'),struct.unpack_from('>II',data,u+4)))
                        elif prop==b'auxC':
                            require(v-u>=5,'invalid auxC');val['auxiliary_type']=data[u+4:v].split(b'\0')[0].decode('ascii','replace')
                        result['properties'].append(val)
                elif typ==b'ipma':
                    q=data[x:y];require(len(q)>=8,'truncated ipma');width=4 if q[0] else 2;wide=bool(int.from_bytes(q[1:4],'big')&1);count=int.from_bytes(q[4:8],'big');pos=8
                    for _ in range(count):
                        require(pos+width+1<=len(q),'truncated associations');item=int.from_bytes(q[pos:pos+width],'big');pos+=width;n=q[pos];pos+=1;refs=[]
                        for _ in range(n):
                            size=2 if wide else 1;require(pos+size<=len(q),'truncated property index');ref=int.from_bytes(q[pos:pos+size],'big');pos+=size;refs.append(ref&(0x7fff if wide else 0x7f))
                        result['associations'].setdefault(item,[]).extend(refs)
                    require(pos==len(q),'unexpected association trailing bytes')
    for item,refs in result['associations'].items():
        require(item in result['items'],'unknown associated item')
        require(all(0<=i<=len(result['properties']) for i in refs),'invalid property reference')
        props=[result['properties'][i-1] for i in refs if i]
        result['items'][item]['properties']=props
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('files',type=Path,nargs='+');ap.add_argument('--out',type=Path);args=ap.parse_args();rows=[]
    for p in args.files:
        require(p.stat().st_size<=32*1024*1024,'input exceeds metadata inspection size bound')
        rows.append({'path':str(p),'metadata':inspect(p.read_bytes())})
    text=json.dumps(rows,indent=2)+'\n'
    if args.out:args.out.write_text(text)
    else:print(text,end='')
if __name__=='__main__':main()
