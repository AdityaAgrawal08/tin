"""Ordinary code owns filtering, validation and rendering; the model labels one batch."""

import json
from pathlib import Path

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "orders": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "category": {"type": "string", "enum": ["small", "medium", "large"]},
                },
                "required": ["id", "category"],
            },
        }
    },
    "required": ["orders"],
}


async def run(ctx, inputs):
    orders = json.loads(Path("fixtures/orders.json").read_text())  # noqa: ASYNC240
    selected = [row for row in orders if row["amount_cents"] >= inputs["minimum_cents"]]
    response = await ctx.models.generate(
        route="classification",
        step="classify_orders",
        instructions=(
            "Classify every supplied order: small below 1000 cents, medium from 1000 through "
            "1999 cents, large at 2000 cents or more. Return each original ID exactly once."
        ),
        data=selected,
        output_schema=SCHEMA,
    )
    classified = response["parsed"]["orders"]
    labels = {row["id"]: row["category"] for row in classified}
    if len(classified) != len(selected) or set(labels) != {row["id"] for row in selected}:
        raise ValueError("The model changed the order set")
    for row in selected:
        expected = (
            "small"
            if row["amount_cents"] < 1000
            else ("medium" if row["amount_cents"] < 2000 else "large")
        )
        if labels[row["id"]] != expected:
            raise ValueError("The model classification failed the business rule")
    report = [
        "# Classified fixture orders",
        "",
        f"Selected orders: {len(selected)}",
        "",
        "| Order | Amount (cents) | Category |",
        "| --- | ---: | --- |",
        *[f"| {row['id']} | {row['amount_cents']} | {labels[row['id']]} |" for row in selected],
        "",
    ]
    return {"path": "reports/custom/ORDER_CLASSIFICATION.md", "content": "\n".join(report)}
