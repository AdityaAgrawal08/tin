"""Run locally with fixture inputs, or independently in Tin's code executor."""

import json
from pathlib import Path


def run(ctx, inputs):
    orders = json.loads(Path("fixtures/orders.json").read_text())
    selected = [order for order in orders if order["amount_cents"] >= inputs["minimum_cents"]]
    total = sum(order["amount_cents"] for order in selected)
    rows = "\n".join(f"| {order['id']} | {order['amount_cents']} |" for order in selected)
    return {
        "path": "reports/custom/ORDER_REPORT.md",
        "content": (
            "# Fixture order report\n\n"
            f"Minimum order: {inputs['minimum_cents']} cents\n\n"
            f"Selected orders: {len(selected)}\n\nTotal: {total} cents\n\n"
            "| Order | Amount (cents) |\n| --- | ---: |\n" + rows + "\n"
        ),
    }
