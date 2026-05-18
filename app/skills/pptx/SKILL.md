---
name: pptx
description: INVOKE whenever a .pptx file is the deliverable or the input — pitch decks, sales decks, board decks, investor presentations, training material, conference talks, slide redesigns, or extracting text from an existing deck. Triggers — "slides", "deck", "presentation", "pitch", "PowerPoint", "Keynote", "pptx", "investor deck", or any user-supplied .pptx path. Do NOT trigger when the deliverable is a Word doc, PDF report, or HTML page.
---

# PowerPoint (pptx) Skill

## Overview
The deliverable is a **real, polished .pptx file** that opens in PowerPoint/Keynote/Google Slides and looks **deliberately designed** — not the default "title + bullets on white" output. The work runs inside the sandbox using **python-pptx** for authoring and **LibreOffice + pdftoppm** for QA renders.

Write deliverables to `/home/user/workspace/artifacts/`.

## Quick Reference
| Task | How |
|------|-----|
| Extract text from a deck | `python -m markitdown presentation.pptx` |
| Render thumbnails for visual QA | `python /home/user/skills/pptx/scripts/thumbnails.py deck.pptx out/` |
| Create from scratch | `python-pptx` (this skill) — see pattern below |
| Edit an existing deck | Load with python-pptx, modify in place, save |
| Convert to PDF / images | `soffice --headless --convert-to pdf deck.pptx` → `pdftoppm` |

## Authoring Pattern (canonical)

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN

OUT = "/home/user/workspace/artifacts/deck.pptx"

# 16:9 widescreen (default)
prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)

# ── Palette: "Midnight Executive" ──
NAVY   = RGBColor(0x1E, 0x27, 0x61)
ICE    = RGBColor(0xCA, 0xDC, 0xFC)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT = RGBColor(0xF9, 0x61, 0x67)  # coral, used sparingly

blank = prs.slide_layouts[6]  # fully blank — we draw everything explicitly

# ── Title slide (dark) ──
s = prs.slides.add_slide(blank)
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY
bg.line.fill.background()

title = s.shapes.add_textbox(Inches(0.8), Inches(2.4), Inches(11.5), Inches(2)).text_frame
title.word_wrap = True
p = title.paragraphs[0]
p.text = "Why Now"
p.font.size = Pt(72); p.font.bold = True; p.font.color.rgb = WHITE
p.font.name = "Georgia"

sub = s.shapes.add_textbox(Inches(0.8), Inches(4.6), Inches(11.5), Inches(1)).text_frame
sp = sub.paragraphs[0]
sp.text = "A 2026 outlook on enterprise AI infrastructure."
sp.font.size = Pt(20); sp.font.color.rgb = ICE
sp.font.name = "Calibri"

# ── Content slide (light, two-column) ──
s = prs.slides.add_slide(blank)
# Title
t = s.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12.2), Inches(0.9)).text_frame
tp = t.paragraphs[0]
tp.text = "Three forces compressing the timeline"
tp.font.size = Pt(36); tp.font.bold = True; tp.font.color.rgb = NAVY
tp.font.name = "Georgia"

# Left: stat callout
stat = s.shapes.add_textbox(Inches(0.6), Inches(1.8), Inches(5.5), Inches(2)).text_frame
sp = stat.paragraphs[0]
sp.text = "73%"; sp.font.size = Pt(96); sp.font.bold = True; sp.font.color.rgb = ACCENT
sp.font.name = "Arial Black"
sp2 = stat.add_paragraph()
sp2.text = "of CIOs accelerated AI budgets in Q1 2026."
sp2.font.size = Pt(16); sp2.font.color.rgb = NAVY

# Right: bullet column
bul = s.shapes.add_textbox(Inches(7.0), Inches(1.8), Inches(5.8), Inches(4.5)).text_frame
bul.word_wrap = True
for i, line in enumerate([
    "Inference cost down 4x year-over-year",
    "Open-weight models match GPT-4 on enterprise tasks",
    "Procurement cycles compressed from 9 to 3 months",
]):
    p = bul.paragraphs[0] if i == 0 else bul.add_paragraph()
    p.text = f"●  {line}"
    p.font.size = Pt(18); p.font.color.rgb = NAVY; p.font.name = "Calibri"
    p.space_after = Pt(12)

prs.save(OUT)
print(f"Wrote {OUT}")
```

## Design Standards — DON'T ship boring decks

### Before drawing a single slide
- **Pick a bold, content-informed palette.** If your colors would "work" in a totally different deck on a different topic, they aren't specific enough.
- **Dominance over equality.** One color owns 60–70% of the visual weight. 1–2 supporting tones. One sharp accent.
- **Sandwich structure.** Dark backgrounds on title + section dividers + conclusion; light on content slides. Or commit to dark throughout for a premium feel.
- **One repeating motif.** Pick ONE distinctive element (rounded image frames, icons in colored circles, thick single-side borders) and carry it across every slide.

### Palettes (pick one, don't mix)
| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| Midnight Executive | `1E2761` navy | `CADCFC` ice | `F96167` coral |
| Forest & Moss | `2C5F2D` forest | `97BC62` moss | `F5F5F5` cream |
| Coral Energy | `F96167` coral | `F9E795` gold | `2F3C7E` navy |
| Warm Terracotta | `B85042` terracotta | `E7E8D1` sand | `A7BEAE` sage |
| Ocean Gradient | `065A82` deep blue | `1C7293` teal | `21295C` midnight |
| Charcoal Minimal | `36454F` charcoal | `F2F2F2` off-white | `212121` black |
| Teal Trust | `028090` teal | `00A896` seafoam | `02C39A` mint |
| Berry & Cream | `6D2E46` berry | `A26769` dusty rose | `ECE2D0` cream |
| Cherry Bold | `990011` cherry | `FCF6F5` off-white | `2F3C7E` navy |

### Typography
Pair a header font with personality with a clean body font. Don't default to Calibri-on-Calibri.

| Header | Body | Sizes |
|--------|------|-------|
| Georgia | Calibri | Title 40–48pt, Header 22–28pt, Body 14–18pt, Caption 10–12pt |
| Arial Black | Arial | same |
| Cambria | Calibri | same |
| Impact | Arial | same |

### Layout Library (rotate, don't repeat)
- **Two-column** — heading + paragraph left, illustration / chart right
- **Stat callout** — giant number (60–96pt) + supporting clause beside
- **Icon-row** — 3 to 4 icons in colored circles, each with a 2-line caption
- **2×2 / 2×3 grid** — quadrants of insight; pair with a half-bleed image
- **Half-bleed image** — image takes ~45–50% of the slide; content overlays the other side
- **Timeline / process** — numbered nodes joined by lines or arrows

### Slide-Level Rules (every slide)
- Every slide carries a visual element (image, shape, chart, icon). Text-only is forgettable.
- Titles 36pt+, body 14–18pt — size contrast matters more than color contrast.
- Left-align body text. Center titles only.
- 0.5" minimum margins; 0.3–0.5" gap between content blocks (stay consistent).
- High contrast both ways — never light text on light fill or dark text on dark fill.
- **NEVER draw a thin accent line under the title** — that pattern screams "AI-generated".
- Don't style one slide and leave the rest plain. Commit fully or keep it simple throughout.

### Common Mistakes (don't)
- Repeating the same layout on every slide
- Centering body text
- Defaulting to generic blue
- Mixing 0.3" and 0.5" gaps in the same deck
- Forgetting text-frame padding when aligning shapes to text edges (`text_frame.margin_left = 0`)

## QA — Required Before Declaring Success

**Assume there are problems and go find them.** First render is rarely correct.

### 1. Content QA
```bash
python -m markitdown /home/user/workspace/artifacts/deck.pptx
```
Scan for missing content, typos, wrong order. Also grep for stray placeholder text:
```bash
python -m markitdown deck.pptx | grep -iE "xxxx|lorem|ipsum|placeholder|TBD"
```

### 2. Visual QA
Render slides to JPGs and look at them:
```bash
python /home/user/skills/pptx/scripts/thumbnails.py /home/user/workspace/artifacts/deck.pptx /home/user/workspace/artifacts/slides/
```
Then for each slide image, check for:
- Overlapping elements (text through shapes, lines through words)
- Text overflow or cut at box boundaries
- Decorative shapes positioned for single-line title but the title wrapped to two
- Source citations or footers colliding with content above
- Elements <0.3" apart (cramped) or huge uneven empty areas
- Insufficient slide-edge margin (<0.5")
- Columns / repeated elements not aligned consistently
- Low-contrast text or icons
- Leftover placeholder content

### 3. Verification Loop
1. Generate → render → inspect
2. List issues (if you found "zero", look again more critically)
3. Fix
4. **Re-render the affected slides** — one fix often creates the next problem
5. Repeat until a full pass surfaces no new issues

**Do not declare success without at least one fix-and-verify cycle.**

## Editing Existing Decks
- Load with `Presentation('input.pptx')` — preserves layouts, masters, theme
- Iterate `prs.slides`, then `slide.shapes` / `shape.text_frame.paragraphs[i].runs[j]`
- Match the existing font, color, and spacing of the deck — do NOT impose this skill's design system on a deck with established conventions
- Re-render and run the visual QA pass after every meaningful change

## Dependencies (installed in the e2b template)
- `python-pptx` — authoring/editing
- `markitdown[pptx]` — text extraction
- `Pillow` — image manipulation for thumbnails
- `libreoffice` (`soffice`) — PDF / image conversion
- `poppler-utils` (`pdftoppm`) — PDF to JPG

## Final Step
1. Save artifact to `/home/user/workspace/artifacts/`
2. Run the full QA loop until clean
3. `write_to_shared_memory(key="artifact:deck", value="<absolute path>")`
4. In your final response, summarise the deck's structure (slide titles) and call out any design choices the user should know about — don't dump slide bodies.
