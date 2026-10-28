#!/usr/bin/env python3
"""Derive exact media layout from the generated target headers; no system writes."""
from pathlib import Path
import re,argparse
ROOT=Path(__file__).resolve().parents[1]
def generate():
 va=(ROOT/'NootedRed/VDAVADataSequoia24H232.hpp').read_text();gva=(ROOT/'NootedRed/VDAGVADataSequoia24H232.hpp').read_text()
 image=int(re.search(r'ImageBase = (0x[0-9A-Fa-f]+)',va)[1],16)
 offsets=[int(x,16) for x in re.findall(r'// Page \d+:.*image offset (0x[0-9A-Fa-f]+)',va)];assert len(offsets)==9
 text='// Exact 24H232 reference layout, derived from generated headers by tools/gen_media_layout.py.\n#pragma once\n#include <MediaExactPlan.hpp>\n#include <VDAVADataSequoia24H232.hpp>\n#include <VDAGVADataSequoia24H232.hpp>\nnamespace MediaReference24H232 {\ninline constexpr MediaExactPlan::PageReference Pages[]={\n'
 text+=''.join(f'    {{0x{image-0x7ff800000000+off:X}ULL,VDAVADataSequoia24H232::Page{i}}},\n' for i,off in enumerate(offsets))
 addr=int(re.search(r'// source page: (0x[0-9a-f]+)',gva)[1],16)-0x7ff800000000
 return text+f'    {{0x{addr:X}ULL,VDAGVADataSequoia24H232::Page0}},\n'+'};\n}\n'
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();target=ROOT/'NootedRed/MediaReference24H232.hpp';text=generate()
 if a.check:assert target.read_text()==text,'Media layout differs from source header metadata'
 else:target.write_text(text)
 print('Exact media layout verified' if a.check else 'Generated exact media layout')
