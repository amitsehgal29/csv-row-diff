# csv-row-diff

Compare two CSV snapshots of the same table (for example yesterday's and today's extract), matched on a key, and see exactly which rows were **inserted**, **deleted** or **updated**. For updates it also lists which columns changed, with old and new values. Python 3 standard library only.

Use it to check what a source actually changed before an incremental load, to review a backfill, or as a CI gate on a reference-data file.

## Usage

```bash
python3 csv_row_diff.py samples/orders_yesterday.csv samples/orders_today.csv --key order_id --ignore updated_at
```

Options:

- `--key id,date` uses a composite key.
- `--compare a,b` compares only those columns. By default it compares every non-key column in either file.
- `--ignore updated_at` skips noisy columns such as load timestamps.
- `--normalize` trims values and lowercases keys before comparing.
- `--max-changes N` caps the listed changes (default 50; 0 means no cap).

Exit codes: `0` no differences, `1` differences found, `2` bad input (missing key column, or duplicate keys in either file, which are listed).

## Example output (real run on the samples)

```json
{
  "old_rows": 4,
  "new_rows": 4,
  "keys": ["order_id"],
  "columns_compared": ["customer", "status", "amount"],
  "inserted": 1,
  "deleted": 1,
  "updated": 2,
  "unchanged": 1,
  "changes": [
    {"change": "deleted", "key": {"order_id": "1003"},
     "old": {"order_id": "1003", "customer": "Sam", "status": "pending", "amount": "80.00", "updated_at": "2026-11-08T12:00:00Z"}},
    {"change": "updated", "key": {"order_id": "1001"}, "columns": ["status"],
     "old": {"status": "pending"}, "new": {"status": "shipped"}},
    {"change": "updated", "key": {"order_id": "1004"}, "columns": ["amount"],
     "old": {"amount": "15.50"}, "new": {"amount": "19.50"}},
    {"change": "inserted", "key": {"order_id": "1005"},
     "new": {"order_id": "1005", "customer": "Maya", "status": "pending", "amount": "200.00", "updated_at": "2026-11-09T10:00:00Z"}}
  ],
  "changes_truncated": false
}
```

(Reformatted for width; the tool prints the same JSON with one field per line. Exit code was 1.)

## Tests

```bash
python3 -m unittest -v
```
