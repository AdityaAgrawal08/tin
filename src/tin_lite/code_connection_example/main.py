"""Fetch three accounts, filter in Python, classify once, validate, and report."""

import re

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "accounts": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "segment": {"type": "string", "enum": ["small", "midmarket"]},
                },
                "required": ["id", "segment"],
            },
        }
    },
    "required": ["accounts"],
}


async def run(ctx, inputs):
    response = await ctx.services.request(
        service="crm", step="fetch_accounts", path="/accounts", params={"limit": 3}
    )
    if response["status"] != 200:
        raise ValueError("The API did not return the requested accounts")
    accounts = response["data"]["accounts"]
    if not isinstance(accounts, list) or not 1 <= len(accounts) <= 3:
        raise ValueError("Invalid account list")
    for row in accounts:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "employees"}
            or not isinstance(row["id"], str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", row["id"])
            or type(row["employees"]) is not int
            or not 0 <= row["employees"] <= 1_000_000
        ):
            raise ValueError("Invalid account record")
    if len({row["id"] for row in accounts}) != len(accounts):
        raise ValueError("Duplicate account IDs")
    selected = [row for row in accounts if row["employees"] >= inputs["minimum_employees"]]
    labels = {}
    if selected:
        response = await ctx.models.generate(
            route="classification",
            step="classify_accounts",
            instructions=(
                "Classify each supplied account: small below 50 employees, "
                "midmarket at 50 or more. Return each original ID exactly once."
            ),
            data=selected,
            output_schema=SCHEMA,
        )
        classified = response["parsed"]["accounts"]
        labels = {row["id"]: row["segment"] for row in classified}
        if len(classified) != len(selected) or set(labels) != {row["id"] for row in selected}:
            raise ValueError("The model changed the account set")
        if any(
            labels[row["id"]] != ("small" if row["employees"] < 50 else "midmarket")
            for row in selected
        ):
            raise ValueError("Classification failed the business rule")
    report = [
        "# Connected account report",
        "",
        f"Fetched: {len(accounts)} · Selected: {len(selected)}",
        "",
        "| Account | Employees | Segment |",
        "| --- | ---: | --- |",
        *[f"| {row['id']} | {row['employees']} | {labels[row['id']]} |" for row in selected],
        "",
        "API requests use the connected provider account; its cost is unreported.",
        "Tin model usage and credits are recorded separately in run usage.",
        "",
    ]
    return {"path": "reports/custom/CONNECTED_ACCOUNTS.md", "content": "\n".join(report)}
