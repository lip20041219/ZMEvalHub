"""``zmeval`` CLI.

P0.0 exposes two commands only:

* ``zmeval validate <file>`` — validate a JSON file against the v1 contract.
* ``zmeval schema [--out PATH]`` — emit the JSON Schema.

Exit codes follow the blueprint's CI convention (§9.3): 0 success, 3 usage /
config error. A validation failure exits 1 so it can gate a pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zmevalhub.schemas.v1 import model_json_schema
from zmevalhub.validation import validate_file

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 3


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return EXIT_USAGE

    result = validate_file(path)
    print(result.render())
    if args.json:
        print(
            json.dumps(
                {"ok": result.ok, "issues": [i.__dict__ for i in result.issues]},
                ensure_ascii=False,
                indent=2,
            )
        )
    return EXIT_OK if result.ok else EXIT_INVALID


def _cmd_schema(args: argparse.Namespace) -> int:
    schema = model_json_schema()
    text = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    else:
        sys.stdout.write(text)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zmeval", description="ZMEvalHub CLI (P0.0)")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="Validate a JSON file against schema_version=1")
    v.add_argument("file", help="Path to the JSON file")
    v.add_argument("--json", action="store_true", help="Also emit machine-readable issues")
    v.set_defaults(func=_cmd_validate)

    s = sub.add_parser("schema", help="Print or write the JSON Schema")
    s.add_argument("--out", help="Write schema JSON to this path instead of stdout")
    s.set_defaults(func=_cmd_schema)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
