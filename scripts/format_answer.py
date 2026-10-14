#!/usr/bin/env python3
"""Source-traceability mode.

Only used when the user explicitly asks for the page number, the original
wording, the record id or the review status. The default answer path never
surfaces these fields.

    python3 scripts/format_answer.py --query "便血 第16方"
    python3 scripts/format_answer.py --id F0123 --fields title,book_page,raw
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from search import load_records, run_search  # noqa: E402

ALL_FIELDS = [
    "id", "chapter", "condition", "condition_no", "formula_no", "title",
    "name", "ingredients", "usage", "effect", "pdf_page", "book_page",
    "source_refs", "raw", "review",
]

TRACE_FIELDS = [
    "id", "chapter", "condition", "formula_no", "title", "pdf_page",
    "book_page", "source_refs", "raw",
]


def project(record: dict, fields: list[str]) -> dict:
    return {field: record.get(field) for field in fields if field in record}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--id", default=None)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--fields", default="")
    parser.add_argument("--records", default=str(SKILL_ROOT / "assets" / "records.jsonl"))
    args = parser.parse_args()

    records = load_records(Path(args.records))
    fields = [f.strip() for f in args.fields.split(",") if f.strip()] or TRACE_FIELDS
    unknown = [f for f in fields if f not in ALL_FIELDS]
    if unknown:
        raise SystemExit(f"unknown fields: {', '.join(unknown)}")

    if args.id:
        matches = [r for r in records if r.get("id") == args.id]
    elif args.query:
        matches = run_search(args.query, records, args.limit)["results"]
        by_id = {r["id"]: r for r in records}
        matches = [by_id[m["id"]] for m in matches if m["id"] in by_id]
    else:
        parser.error("需要 --query 或 --id")

    payload = {
        "query": args.query or args.id,
        "count": len(matches),
        "records": [project(record, fields) for record in matches],
        "disclaimer": "来源核对只确认转录与原页一致，不代表临床有效性或安全性评价。",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
