"""A deterministic workflow: parse, validate, calculate, render."""

import csv
import io
import re


def run(ctx, inputs):
    reader = csv.DictReader(io.StringIO(inputs["csv_text"]))
    headers = reader.fieldnames or []
    if "amount_cents" not in headers or len(headers) != len(set(headers)):
        raise ValueError("Use unique column names, including amount_cents")
    amounts = []
    for row in reader:
        value = row.get("amount_cents")
        if None in row or any(item is None for item in row.values()):
            raise ValueError("Each row must match the header")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,10}", value):
            raise ValueError("amount_cents must be a non-negative integer of at most 10 digits")
        amounts.append(int(value))
    if not amounts:
        raise ValueError("Provide at least one data row")
    return {
        "path": "reports/CSV_SUMMARY.md",
        "content": (
            f"# CSV summary\n\nRows: {len(amounts)}\n\nTotal amount (cents): {sum(amounts)}\n"
        ),
    }
