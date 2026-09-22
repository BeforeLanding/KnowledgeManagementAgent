"""Run the deterministic, model-free synthetic retrieval benchmark."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.evaluation import evaluate_synthetic_suite  # noqa: E402


def main() -> None:
    result = evaluate_synthetic_suite(ROOT / "evaluations" / "week3-synthetic-retrieval.json")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
