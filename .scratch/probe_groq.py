import sys, time
sys.path.insert(0, "src")
from deckforge.inference.factory import vlm_judge
from deckforge.registry import get_prompt_registry
judge = vlm_judge("vlm_judge", use_cache=False)
print("модель:", judge.client.model)
from pathlib import Path
img = sorted(Path(".scratch/VKTec/png").glob("*.png"))[0]
t = time.perf_counter()
from deckforge.audit.semantic.judge import ask, QUESTIONS
q_id, q = next(iter(QUESTIONS.items()))
v = ask(judge, check_id=q_id, question=q, image_png=img.read_bytes(), language="ru", context="", votes=1)
print(f"{time.perf_counter()-t:.1f} c, вердикт: {v}")
