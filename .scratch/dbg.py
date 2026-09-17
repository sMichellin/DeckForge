import asyncio, sys
sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
from pathlib import Path
from bench_audit_calibration import build_deck, measure
from deckforge.parsing import TemplateParser
from deckforge.layout.fonts import FontLibrary
from deckforge.audit.runner import AuditRunner
from deckforge.domain.content import Brief, ContentPackage
m = TemplateParser().parse(Path(".scratch/t.pptx"))
print("макетов:", len(m.layouts))
deck, notes = build_deck(m, FontLibrary.default())
print("слайдов:", len(deck.slides), "notes:", notes)
c = ContentPackage(brief=Brief(purpose="report", audience="x", target_slides=10))
r = AuditRunner()
rep = asyncio.run(r.run(deck, m, c))
print("findings:", len(rep.findings), "summary:", rep.summary)
print("skipped:", len(r.skipped_checks), r.skipped_checks)
print("overflow blocks:", [(s.slide_id, bid) for s in deck.slides for bid,f in s.fit_report.items() if f.overflow])
