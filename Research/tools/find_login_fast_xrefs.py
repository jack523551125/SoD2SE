"""Fast RIP-relative xrefs for selected exact strings in the pinned PE image."""
import json, re, struct, sys
from pe_static import PeImage
image=PeImage(sys.argv[1])
needles=[b"FrontendLoginCallbackProxy.cpp",b"SaveGame_NoUser",b"Login_NoOfflineCredentials",b"ApiOfflinePlayer"]
targets={}
for needle in needles:
 start=0
 while (offset:=image.data.find(needle,start))>=0:
  for sec in image.sections:
   if sec.raw_offset<=offset<sec.raw_offset+sec.raw_size:
    targets[sec.virtual_address+offset-sec.raw_offset]=needle.decode(); break
  start=offset+1
rows=[]
pat=re.compile(rb"[\x40-\x4f][\x8d\x8b\x89][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....",re.DOTALL)
for sec in image.sections:
 if not sec.is_executable: continue
 code=image.data[sec.raw_offset:sec.raw_offset+sec.raw_size]
 for m in pat.finditer(code):
  site=sec.virtual_address+m.start()
  target=site+7+struct.unpack_from("<i",m.group(),3)[0]
  if target in targets: rows.append(dict(string=targets[target],site_rva=hex(site),target_rva=hex(target)))
print(json.dumps(rows,indent=2))
