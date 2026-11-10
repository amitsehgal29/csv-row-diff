#!/usr/bin/env python3
"""csv-row-diff: compare two CSV snapshots by key and report row changes.

Standard library only. Classifies each key as inserted, deleted, updated or
unchanged, and lists the columns that changed on updates.
"""
import argparse
import csv
import json
import sys


def read_rows(handle):
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        return [], []
    fieldnames = list(reader.fieldnames)
    return fieldnames, list(reader)


def parse_columns(value):
    return [part.strip() for part in value.split(",") if part.strip()]


def key_of(row, keys, normalize):
    values = [(row.get(k) or "") for k in keys]
    if normalize:
        values = [v.strip().lower() for v in values]
    return tuple(values)


def cell(row, column, normalize):
    value = row.get(column)
    if value is None:
        value = ""
    if normalize:
        return value.strip()
    return value


def index_by_key(rows, keys, normalize):
    """Map each key to (1-based data row number, row).

    Returns (index, duplicates) where duplicates maps key tuples to row numbers
    for keys that appear more than once.
    """
    index = {}
    seen = {}
    for i, row in enumerate(rows, start=1):
        k = key_of(row, keys, normalize)
        seen.setdefault(k, []).append(i)
        if k not in index:
            index[k] = (i, row)
    duplicates = {k: nums for k, nums in seen.items() if len(nums) > 1}
    return index, duplicates


def compared_columns(old_fields, new_fields, keys, compare=None, ignore=None):
    if compare:
        cols = list(compare)
    else:
        seen = []
        for name in list(old_fields) + list(new_fields):
            if name not in seen:
                seen.append(name)
        cols = [name for name in seen if name not in keys]
    if ignore:
        ignored = set(ignore)
        cols = [name for name in cols if name not in ignored]
    return cols


def changed_columns(old_row, new_row, columns, normalize):
    return [
        name
        for name in columns
        if cell(old_row, name, normalize) != cell(new_row, name, normalize)
    ]


def key_record(keys, key):
    return dict(zip(keys, key))


def diff_snapshots(old_rows, new_rows, keys, columns, normalize=False):
    old_index, old_dups = index_by_key(old_rows, keys, normalize)
    new_index, new_dups = index_by_key(new_rows, keys, normalize)
    if old_dups or new_dups:
        return None, old_dups, new_dups

    inserted = []
    deleted = []
    updated = []
    unchanged = 0

    for key, (_line, old_row) in old_index.items():
        if key not in new_index:
            deleted.append(
                {
                    "change": "deleted",
                    "key": key_record(keys, key),
                    "old": dict(old_row),
                }
            )
            continue
        _line, new_row = new_index[key]
        changed = changed_columns(old_row, new_row, columns, normalize)
        if not changed:
            unchanged += 1
            continue
        updated.append(
            {
                "change": "updated",
                "key": key_record(keys, key),
                "columns": changed,
                "old": {name: old_row.get(name, "") or "" for name in changed},
                "new": {name: new_row.get(name, "") or "" for name in changed},
            }
        )

    for key, (_line, new_row) in new_index.items():
        if key not in old_index:
            inserted.append(
                {
                    "change": "inserted",
                    "key": key_record(keys, key),
                    "new": dict(new_row),
                }
            )

    report = {
        "old_rows": len(old_rows),
        "new_rows": len(new_rows),
        "keys": keys,
        "columns_compared": columns,
        "inserted": len(inserted),
        "deleted": len(deleted),
        "updated": len(updated),
        "unchanged": unchanged,
        "changes": deleted + updated + inserted,
    }
    return report, old_dups, new_dups


def format_duplicates(keys, dups):
    return [
        {"key": key_record(keys, key), "rows": rows}
        for key, rows in dups.items()
    ]


def missing_columns(fieldnames, required):
    return [name for name in required if name not in fieldnames]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare two CSV snapshots by key and report inserted, deleted and updated rows."
    )
    parser.add_argument("old", help="older CSV snapshot")
    parser.add_argument("new", help="newer CSV snapshot")
    parser.add_argument(
        "-k",
        "--key",
        required=True,
        help="comma-separated key columns, e.g. order_id or id,date",
    )
    parser.add_argument(
        "--compare",
        help="comma-separated columns to compare (default: every non-key column in either file)",
    )
    parser.add_argument(
        "--ignore",
        help="comma-separated columns to skip when deciding whether a row changed",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="trim values and lowercase keys before comparing",
    )
    parser.add_argument(
        "--max-changes",
        type=int,
        default=50,
        help="cap the listed changes (default: 50; 0 means no cap)",
    )
    args = parser.parse_args(argv)

    keys = parse_columns(args.key)
    if not keys:
        print("csv-row-diff: --key is required", file=sys.stderr)
        return 2

    try:
        with open(args.old, newline="", encoding="utf-8") as handle:
            old_fields, old_rows = read_rows(handle)
        with open(args.new, newline="", encoding="utf-8") as handle:
            new_fields, new_rows = read_rows(handle)
    except OSError as exc:
        print(f"csv-row-diff: {exc}", file=sys.stderr)
        return 2

    missing_old = missing_columns(old_fields, keys)
    missing_new = missing_columns(new_fields, keys)
    if missing_old or missing_new:
        parts = []
        if missing_old:
            parts.append(f"old file missing key column(s): {', '.join(missing_old)}")
        if missing_new:
            parts.append(f"new file missing key column(s): {', '.join(missing_new)}")
        print("csv-row-diff: " + "; ".join(parts), file=sys.stderr)
        return 2

    compare = parse_columns(args.compare) if args.compare else None
    ignore = parse_columns(args.ignore) if args.ignore else None
    if compare:
        missing = missing_columns(set(old_fields) | set(new_fields), compare)
        if missing:
            print(
                "csv-row-diff: --compare column(s) not in either file: "
                + ", ".join(missing),
                file=sys.stderr,
            )
            return 2

    columns = compared_columns(old_fields, new_fields, keys, compare, ignore)
    report, old_dups, new_dups = diff_snapshots(
        old_rows, new_rows, keys, columns, normalize=args.normalize
    )
    if old_dups or new_dups:
        payload = {
            "error": "duplicate_keys",
            "old": format_duplicates(keys, old_dups),
            "new": format_duplicates(keys, new_dups),
        }
        print(json.dumps(payload, indent=2))
        return 2

    changes = report["changes"]
    if args.max_changes >= 0:
        cap = args.max_changes
        report["changes_truncated"] = cap != 0 and len(changes) > cap
        if cap != 0:
            report["changes"] = changes[:cap]
    print(json.dumps(report, indent=2))
    if report["inserted"] or report["deleted"] or report["updated"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
