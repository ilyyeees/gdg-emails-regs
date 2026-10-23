#!/usr/bin/env python3
"""Dependency-free static validation. This does not emulate inbox rendering."""
from pathlib import Path
from html.parser import HTMLParser
import json,re,zipfile
R=Path(__file__).resolve().parents[1]
BASE='https://ilyyeees.github.io/gdg-emails-regs/'
class Tables(HTMLParser):
 def __init__(self):super().__init__();self.stack=[];self.images=[]
 def handle_starttag(self,tag,attrs):
  if tag in ('table','tr','td'):self.stack.append(tag)
  if tag=='img':self.images.append(dict(attrs))
 def handle_endtag(self,tag):
  if tag in ('table','tr','td'):assert self.stack and self.stack.pop()==tag, f'Unbalanced {tag}'
D=json.loads((R/'departments.json').read_text())
assert len(D)==10
for d in D:
 p=R/'emails'/f'{d["slug"]}.html';s=p.read_text();v=Tables();v.feed(s)
 assert not v.stack,p
 assert set(re.findall(r'{{(.*?)}}',s))=={'first_name','next_step_text','next_step_url'},p
 assert not re.search(r'CHAPTER [IVX]+<',s),p
 assert len(s.encode())<20000,p
 assert not re.search(r'<script|display\s*:\s*(flex|grid)|data:image',s),p
 assert 'You’ve been accepted' in s and d['name'].replace('&','&amp;') in s,p
 for im in v.images:
  assert 'alt' in im,(p,im)
  assert im['src'].startswith(BASE),(p,im)
  assert (R/im['src'][len(BASE):]).is_file(),(p,im)
 assert (R/'emails'/f'{d["slug"]}.txt').is_file(),p
 print(f'{d["name"]}: balanced tables, placeholders, {len(v.images)} HTTPS image references, {len(s.encode())} bytes')
zip_path=R/'gdg-ensia-acceptance-emails.zip'
if zip_path.exists():
 with zipfile.ZipFile(zip_path) as z:
  assert z.testzip() is None
  assert len(z.namelist())==21
  for d in D:
   for ext in ('html','txt'):
    f=f'emails/{d["slug"]}.{ext}';assert z.read(f)==(R/f).read_bytes(),f
 print('ZIP: 21 entries; integrity and template bytes match.')
print('Static validation passed. Perform separate browser and real inbox checks.')
