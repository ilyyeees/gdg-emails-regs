#!/usr/bin/env python3
"""Package only user-facing templates; no sending or recipient processing."""
from pathlib import Path
import zipfile
R=Path(__file__).resolve().parents[1]
with zipfile.ZipFile(R/'gdg-ensia-acceptance-emails.zip','w',zipfile.ZIP_DEFLATED) as z:
 z.write(R/'departments.json','departments.json')
 for p in sorted((R/'emails').glob('*')): z.write(p,'emails/'+p.name)
print('Created HTML bundle.')
