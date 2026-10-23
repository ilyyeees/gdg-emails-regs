#!/usr/bin/env python3
"""Package only user-facing templates; no sending or recipient processing."""
from pathlib import Path
import zipfile
R=Path(__file__).resolve().parents[1]
readme='''GDG ENSIA — ACCEPTANCE EMAILS

10 ready-to-personalize HTML templates and plain-text alternatives.

Replace every occurrence before sending:
{{first_name}} — recipient’s first name (HTML-escape in HTML).
{{next_step_text}} — real next-step instructions (HTML-escape in HTML).
{{next_step_url}} — real absolute HTTPS link (attribute-escape in HTML).

The images use absolute public HTTPS URLs hosted in the project’s GitHub Pages.
Keep the repository and Pages hosting available when sending these emails.

Suggested subjects are in departments.json. Nothing has been sent. No dates,
chat groups, deadlines or meetings were invented. No name injection or sending
code is included. Test a real message in your intended email clients before
sending to recipients; browser previews are not inbox-client certification.

The decorative parchment-header background is optional: clients that ignore it
still show the complete acceptance letter on solid parchment. Torn-edge artwork,
department relics, and wax seals are regular images. All important text is HTML.

Preview: https://ilyyeees.github.io/gdg-emails-regs/index.html
Source: https://github.com/ilyyeees/gdg-emails-regs
'''
with zipfile.ZipFile(R/'gdg-ensia-acceptance-emails.zip','w',zipfile.ZIP_DEFLATED) as z:
 z.writestr('README.txt',readme)
 z.write(R/'departments.json','departments.json')
 for p in sorted((R/'emails').glob('*')): z.write(p,'emails/'+p.name)
print('Created HTML bundle.')
