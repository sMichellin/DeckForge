"""Колода из макетов настоящего шаблона + превью для судьи (короткие тексты)."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from pathlib import Path
from bench_audit_calibration import text_placeholders
from deckforge.parsing import TemplateParser
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.fitting import fit_slide
from deckforge.layout.errors import LayoutFitError
from deckforge.export.pptx import export_pptx
from deckforge.audit.preview import render_deck_previews
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, DeckIR, SlideIR, TextBlock
from deckforge.rendering.writer import WriterError

TITLES = ["Спрос вырос", "Сроки сократились", "Отток упал", "Команда выросла",
          "Издержки снизились", "Партнёры вернулись", "Поддержка ускорилась", "Рынок сместился"]
BULLETS = ["Меньше ручной работы", "Быстрее согласование", "Проще подключение", "Ниже нагрузка"]

src = Path(sys.argv[1]); out = Path(sys.argv[2]); limit = int(sys.argv[3]) if len(sys.argv) > 3 else 6
out.mkdir(parents=True, exist_ok=True)
m = TemplateParser(cache_dir=out / "cache").parse(src)
fonts = FontLibrary.default()
print(f"шаблон: {m.source_name}, макетов {len(m.layouts)}")

fitted = []; errs = []; overflowed = []
for i, layout in enumerate(m.layouts):
    t_idx, b_idx = text_placeholders(layout)
    if t_idx is None and b_idx is None:
        continue
    blocks = []
    if t_idx is not None:
        blocks.append(TextBlock(block_id="t", placeholder_idx=t_idx, role=TextRole.TITLE,
                                text=TITLES[i % len(TITLES)]))
    if b_idx is not None:
        blocks.append(BulletsBlock(block_id="b", placeholder_idx=b_idx, role=TextRole.BODY,
                                   items=[BulletItem(text=BULLETS[i % len(BULLETS)]),
                                          BulletItem(text=BULLETS[(i + 1) % len(BULLETS)])]))
    slide = SlideIR(slide_id=f"s{i + 1:02d}", layout_id=layout.layout_id, variant="A", blocks=blocks)
    try:
        s = fit_slide(slide, m, fonts=fonts)
    except LayoutFitError as e:
        errs.append(str(e)[:80]); continue
    over = [bid for bid, f in s.fit_report.items() if f.overflow]
    if over:
        overflowed.append((slide.slide_id, layout.name[:30], over)); continue
    fitted.append(s)

print(f"пригодных {len(fitted)}, переполнение {len(overflowed)}, ошибок вписывания {len(errs)}")
for x in overflowed[:6]: print("   переполнение:", x)
for e in errs[:4]: print("   ошибка:", e)
deck = DeckIR(deck_id=m.source_name, variant="A", template_id=m.template_id, seed=1337,
              slides=fitted[:limit])
content = ContentPackage(brief=Brief(purpose="report", audience="команда",
                                     target_slides=max(1, len(deck.slides))))
try:
    pptx = export_pptx(deck, m, src, out / "deck.pptx", content=content)
except WriterError as e:
    print("ПИСАТЕЛЬ ОТКАЗАЛ:", str(e)[:300]); raise SystemExit(2)
previews = render_deck_previews(pptx, deck, out / "png")
print(f"слайдов {len(deck.slides)}, превью {len(previews)}")
(out / "deck.json").write_text(deck.model_dump_json(indent=2), encoding="utf-8")
(out / "previews.json").write_text(json.dumps({k: str(v) for k, v in previews.items()},
                                              ensure_ascii=False), encoding="utf-8")
