from database import get_conn
from engines.prop_engine import PropEngine


db = get_conn()

engine = PropEngine(db)

result = engine.get_best_prop("A'ja Wilson")

print(result)