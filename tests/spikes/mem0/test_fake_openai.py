import math
import runpy
from pathlib import Path


def test_embedding_is_deterministic_normalized_and_bounded() -> None:
    root = Path(__file__).resolve().parents[3]
    module = runpy.run_path(str(root / "docker" / "mem0" / "fake_openai.py"))
    embedding = module["deterministic_embedding"]

    first = embedding("zebra memory")
    second = embedding("zebra memory")

    assert first == second
    assert len(first) == 1536
    assert math.isclose(sum(value * value for value in first), 1.0)
    assert embedding("different memory") != first
