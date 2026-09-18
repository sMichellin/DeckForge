"""Стабильность вердиктов VLM-судьи на трёх прогонах. Критерий выхода change (18)."""
import json, sys, time
sys.path.insert(0, "src")
from pathlib import Path
from deckforge.audit.geometry import slide_text
from deckforge.audit.semantic.judge import QUESTIONS, ask
from deckforge.domain.slide import DeckIR
from deckforge.inference.factory import vlm_judge

work = Path(sys.argv[1]); runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
deck = DeckIR.model_validate_json((work / "deck.json").read_text(encoding="utf-8"))
previews = {k: Path(v).read_bytes() for k, v in
            json.loads((work / "previews.json").read_text(encoding="utf-8")).items()}
slides = list(deck.slides)
print(f"слайдов {len(slides)}, вопросов {len(QUESTIONS)}, прогонов {runs}", flush=True)

results: dict[str, dict[str, str]] = {}
calls = 0
started = time.perf_counter()
for run in range(runs):
    judge = vlm_judge("vlm_judge", use_cache=False)   # кэш обязан быть выключен
    for index, slide in enumerate(slides):
        image = previews.get(slide.slide_id)
        if image is None:
            continue
        for check_id, question in QUESTIONS.items():
            context = ""
            if check_id == "content.neighbours_connected":
                if index == 0:
                    continue
                context = f"Предыдущий слайд: {slide_text(slides[index - 1])[:600]}"
            for attempt in range(4):
                try:
                    v = ask(judge, check_id=check_id, question=question, image_png=image,
                            language=deck.language, context=context, votes=1)
                    break
                except Exception as e:           # лимит токенов Groq — ждём и повторяем
                    if attempt == 3:
                        v = None
                        print(f"  ! сдаюсь на {check_id}/{slide.slide_id}: {str(e)[:120]}", flush=True)
                        break
                    time.sleep(8 * (attempt + 1))
            calls += 1
            cell = f"{slide.slide_id}|{check_id}"
            verdict = "нет ответа" if v is None else ("ok" if v.ok else "находка")
            results.setdefault(cell, {})[f"run{run}"] = verdict
    print(f"прогон {run + 1}/{runs} готов, вызовов {calls}, "
          f"{time.perf_counter() - started:.0f} c", flush=True)

(work / "stability.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
agree = sum(1 for v in results.values() if len(set(v.values())) == 1)
print(f"\nячеек {len(results)}, совпали во всех прогонах {agree} "
      f"({agree / len(results) * 100:.0f} %)")
