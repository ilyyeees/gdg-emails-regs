# GDG ENSIA · The Acceptance Archive

Ten standalone illustrated acceptance email templates, inspired by enchanted grimoires, magical squads, and dark-fantasy engraving.

## Preview and download

- Gallery (when GitHub Pages is enabled): https://ilyyeees.github.io/gdg-emails-regs/
- Download: `gdg-ensia-acceptance-emails.zip`
- Standalone templates: `emails/*.html`
- Plain-text alternatives: `emails/*.txt`
- Suggested subjects and department metadata: `departments.json`

## Before sending

Replace **all three** placeholders in each recipient's HTML and plain text:

| Placeholder | Value |
| --- | --- |
| `{{first_name}}` | HTML-escaped first name in HTML; ordinary text in plain-text version |
| `{{next_step_text}}` | Your real next-step instructions, HTML-escaped |
| `{{next_step_url}}` | Real absolute HTTPS onboarding destination, safely attribute-escaped |

Do not send until the final HTTPS image URLs resolve publicly and all placeholders have been replaced. Review links, copy, and images in a real test message before sending to members. This project deliberately contains no sender, mailing list, name injection script, or tracking pixel. No dates, meetings, chat groups, or deadlines have been invented.

## Departments

Events, Multimedia, Production, Mobile Development, Web Development, Relex, UI/UX, Robotics, AI, Graphic Design.

## Email implementation

- Maximum width 680px with fluid presentation tables and inline CSS.
- Live acceptance copy, department, personal greeting, next-step instructions, and CTA.
- CSS media query enhancements; no layout-critical flex, grid, JavaScript, web fonts, SVG, or background images inside emails.
- Explicit HTML colors and a light color-scheme preference. Dark-mode rewriting remains client-dependent.
- Meaningful alt text on primary illustrations; decorative repeats have empty alt text.
- Classic desktop Outlook receives table width fallback. Serif/system font fallbacks are intentional.
- Each letter reuses its generated department relic in the hero and squad section, plus a shared illustrated acceptance seal.

## Asset hosting

All email image URLs use `https://ilyyeees.github.io/gdg-emails-regs/assets/`. Enable GitHub Pages from **main / root** in repository Settings → Pages. The gallery uses relative paths; downloaded email HTML intentionally keeps absolute public URLs.

Generated art is in `assets/`, optimized as transparent indexed PNG. Source art is archived separately in `artwork-sources.zip` if present. `scripts/optimize-assets.js` only resizes and re-encodes artwork; it does not generate or redraw it. Requires Node.js and Sharp. `python scripts/build.py` regenerates HTML and plain text without any dependencies. Do not edit generated HTML and then rebuild unless you have carried the change into the generator.

## Brand provenance

`assets/gdg-official.png` is the unmodified colored GDG mark downloaded from the site header of the chapter's official website, https://sites.google.com/ensia.edu.dz/gdgcensia/gdgc , linked by the chapter's https://linktr.ee/gdg.ensia profile. It is not AI-generated or recolored. Chapter wording alongside it is real HTML text. See `asset-provenance.json` for the exact source URL.

The departmental relics and acceptance seal are original AI-generated fantasy illustrations, not official GDG insignia or Black Clover assets. No franchise characters or logos are used. The four-leaf seal is decorative artwork, not an official chapter seal.

## Validation

Static checks cover all ten templates: complete placeholder sets, public HTTPS image paths, table-based structure, descriptive primary-image alt text, and HTML under 9 KB per letter. Browser rendering is **not** inbox-client certification. Gmail, Apple Mail, Outlook, and mobile clients may transform CSS, colors, and image display. A real inbox test is still required before production sending.

The raster blackletter heading uses **Pirata One**, copyright Rodrigo Fuenzalida and Nicolas Massi, distributed under the SIL Open Font License 1.1. The unmodified font and license are bundled in `assets/fonts/`. Source: https://github.com/google/fonts/tree/main/ofl/pirataone . Only the decorative heading is rasterized; the acceptance and all actionable content remain real HTML.
