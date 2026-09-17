import sys; sys.path.insert(0,'src')
from deckforge.audit.runner import AuditRunner
from deckforge.audit.registry import REGISTRY
print("после import runner:", len(REGISTRY))
import deckforge.audit.deterministic, deckforge.audit.semantic
print("после import проверок:", len(REGISTRY))
