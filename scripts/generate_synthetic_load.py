"""Generate a bounded company-neutral synthetic load manifest."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.load_testing import (  # noqa: E402
    EXPENSIVE_DOCUMENT_THRESHOLD,
    generate_documents,
    write_manifest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=100)
    parser.add_argument("--seed", type=int, default=606)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-expensive", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.documents >= EXPENSIVE_DOCUMENT_THRESHOLD and not args.confirm_expensive:
            raise ValueError("5k+ generation requires --confirm-expensive")
        documents = generate_documents(args.documents, args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_manifest(args.output, documents, args.seed)
        print(json.dumps({"status": "written", "path": str(args.output), "count": len(documents)}))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
