#!/usr/bin/env python3
import io
import json
import os
import tempfile
import unittest

import csv_row_diff as crd


SAMPLES = os.path.join(os.path.dirname(__file__), "samples")
YESTERDAY = os.path.join(SAMPLES, "orders_yesterday.csv")
TODAY = os.path.join(SAMPLES, "orders_today.csv")


def write_csv(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


class DiffSnapshotsTests(unittest.TestCase):
    def test_sample_snapshots(self):
        with open(YESTERDAY, newline="", encoding="utf-8") as handle:
            _fields, old_rows = crd.read_rows(handle)
        with open(TODAY, newline="", encoding="utf-8") as handle:
            _fields, new_rows = crd.read_rows(handle)
        columns = ["customer", "status", "amount", "updated_at"]
        report, old_dups, new_dups = crd.diff_snapshots(
            old_rows, new_rows, ["order_id"], columns
        )
        self.assertFalse(old_dups)
        self.assertFalse(new_dups)
        self.assertEqual(report["old_rows"], 4)
        self.assertEqual(report["new_rows"], 4)
        self.assertEqual(report["inserted"], 1)
        self.assertEqual(report["deleted"], 1)
        self.assertEqual(report["updated"], 2)
        self.assertEqual(report["unchanged"], 1)
        kinds = [item["change"] for item in report["changes"]]
        self.assertEqual(kinds, ["deleted", "updated", "updated", "inserted"])
        deleted = report["changes"][0]
        self.assertEqual(deleted["key"], {"order_id": "1003"})
        self.assertEqual(deleted["old"]["customer"], "Sam")
        first_update = report["changes"][1]
        self.assertEqual(first_update["key"], {"order_id": "1001"})
        self.assertEqual(first_update["columns"], ["status", "updated_at"])
        self.assertEqual(first_update["old"], {"status": "pending", "updated_at": "2026-11-08T10:00:00Z"})
        self.assertEqual(first_update["new"], {"status": "shipped", "updated_at": "2026-11-09T09:00:00Z"})
        second_update = report["changes"][2]
        self.assertEqual(second_update["key"], {"order_id": "1004"})
        self.assertEqual(second_update["columns"], ["amount", "updated_at"])
        inserted = report["changes"][3]
        self.assertEqual(inserted["key"], {"order_id": "1005"})
        self.assertEqual(inserted["new"]["customer"], "Maya")

    def test_ignore_updated_at(self):
        with open(YESTERDAY, newline="", encoding="utf-8") as handle:
            old_fields, old_rows = crd.read_rows(handle)
        with open(TODAY, newline="", encoding="utf-8") as handle:
            new_fields, new_rows = crd.read_rows(handle)
        columns = crd.compared_columns(
            old_fields, new_fields, ["order_id"], ignore=["updated_at"]
        )
        report, _, _ = crd.diff_snapshots(old_rows, new_rows, ["order_id"], columns)
        self.assertEqual(columns, ["customer", "status", "amount"])
        self.assertEqual(report["updated"], 2)
        updates = [item for item in report["changes"] if item["change"] == "updated"]
        self.assertEqual(updates[0]["columns"], ["status"])
        self.assertEqual(updates[1]["columns"], ["amount"])

    def test_identical_files_are_unchanged(self):
        with open(YESTERDAY, newline="", encoding="utf-8") as handle:
            _fields, rows = crd.read_rows(handle)
        report, _, _ = crd.diff_snapshots(
            rows, rows, ["order_id"], ["customer", "status", "amount", "updated_at"]
        )
        self.assertEqual(report["unchanged"], 4)
        self.assertEqual(report["inserted"], 0)
        self.assertEqual(report["deleted"], 0)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(report["changes"], [])

    def test_composite_key(self):
        old_rows = [
            {"store": "DXB", "sku": "A1", "qty": "2"},
            {"store": "AUH", "sku": "A1", "qty": "5"},
        ]
        new_rows = [
            {"store": "DXB", "sku": "A1", "qty": "3"},
            {"store": "AUH", "sku": "A1", "qty": "5"},
            {"store": "SHJ", "sku": "B2", "qty": "1"},
        ]
        report, _, _ = crd.diff_snapshots(
            old_rows, new_rows, ["store", "sku"], ["qty"]
        )
        self.assertEqual(report["updated"], 1)
        self.assertEqual(report["unchanged"], 1)
        self.assertEqual(report["inserted"], 1)
        self.assertEqual(report["deleted"], 0)
        self.assertEqual(report["changes"][0]["key"], {"store": "DXB", "sku": "A1"})
        self.assertEqual(report["changes"][0]["old"], {"qty": "2"})
        self.assertEqual(report["changes"][0]["new"], {"qty": "3"})

    def test_normalize_trims_and_lowercases_keys(self):
        old_rows = [{"id": " ABC ", "name": " Ali "}]
        new_rows = [{"id": "abc", "name": "Ali"}]
        raw, _, _ = crd.diff_snapshots(old_rows, new_rows, ["id"], ["name"])
        self.assertEqual(raw["inserted"], 1)
        self.assertEqual(raw["deleted"], 1)
        normalized, _, _ = crd.diff_snapshots(
            old_rows, new_rows, ["id"], ["name"], normalize=True
        )
        self.assertEqual(normalized["unchanged"], 1)
        self.assertEqual(normalized["inserted"], 0)
        self.assertEqual(normalized["deleted"], 0)
        self.assertEqual(normalized["updated"], 0)

    def test_duplicate_keys_are_reported(self):
        rows = [
            {"id": "1", "v": "a"},
            {"id": "1", "v": "b"},
            {"id": "2", "v": "c"},
        ]
        report, old_dups, new_dups = crd.diff_snapshots(
            rows, [{"id": "2", "v": "c"}], ["id"], ["v"]
        )
        self.assertIsNone(report)
        self.assertEqual(old_dups, {("1",): [1, 2]})
        self.assertFalse(new_dups)


class CliTests(unittest.TestCase):
    def test_sample_run_exits_one(self):
        code = crd.main([YESTERDAY, TODAY, "--key", "order_id"])
        self.assertEqual(code, 1)

    def test_identical_run_exits_zero(self):
        code = crd.main([YESTERDAY, YESTERDAY, "--key", "order_id"])
        self.assertEqual(code, 0)

    def test_missing_key_column_exits_two(self):
        stderr = io.StringIO()
        old_stderr = crd.sys.stderr
        crd.sys.stderr = stderr
        try:
            code = crd.main([YESTERDAY, TODAY, "--key", "nope"])
        finally:
            crd.sys.stderr = old_stderr
        self.assertEqual(code, 2)
        self.assertIn("missing key column", stderr.getvalue())

    def test_duplicate_keys_cli_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            messy = os.path.join(tmp, "messy.csv")
            write_csv(
                messy,
                "order_id,status\n1001,pending\n1001,shipped\n",
            )
            stdout = io.StringIO()
            old_stdout = crd.sys.stdout
            crd.sys.stdout = stdout
            try:
                code = crd.main([messy, TODAY, "--key", "order_id"])
            finally:
                crd.sys.stdout = old_stdout
            self.assertEqual(code, 2)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["error"], "duplicate_keys")
            self.assertEqual(payload["old"][0]["key"], {"order_id": "1001"})
            self.assertEqual(payload["old"][0]["rows"], [1, 2])

    def test_compare_and_ignore_via_cli(self):
        stdout = io.StringIO()
        old_stdout = crd.sys.stdout
        crd.sys.stdout = stdout
        try:
            code = crd.main(
                [
                    YESTERDAY,
                    TODAY,
                    "--key",
                    "order_id",
                    "--compare",
                    "status,amount,updated_at",
                    "--ignore",
                    "updated_at",
                ]
            )
        finally:
            crd.sys.stdout = old_stdout
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["columns_compared"], ["status", "amount"])
        updates = [item for item in payload["changes"] if item["change"] == "updated"]
        self.assertEqual(updates[0]["columns"], ["status"])
        self.assertEqual(updates[1]["columns"], ["amount"])


if __name__ == "__main__":
    unittest.main()
