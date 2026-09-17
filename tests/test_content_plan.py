from copy import deepcopy
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from tin_lite.content_plan import (
    INPUT_SCHEMA,
    MODEL_SCHEMA,
    ContentPlan,
    bound_schedule,
    empty_plan,
    end_date,
    normalize_model_destinations,
    parse_plan,
    validate_change,
)
from tin_lite.schedules import WorkflowSchedule, next_run_after
from tin_lite.workflow_inputs import validate_input_schema


def fixture_plan():
    return empty_plan(
        uuid4(),
        {
            "audit_run_id": str(uuid4()),
            "keyword_run_id": str(uuid4()),
            "start_date": "2026-09-08",
            "duration": "6_months",
        },
        {"host": "example.com", "market": "US"},
    )


def item(identifier="topic_1"):
    return {
        "id": identifier,
        "title": identifier,
        "brief": "Explain a supported buyer task.",
        "intent": "Buyer implementation",
        "action": "new_page",
        "destination": "",
        "source_ids": ["keyword:k1"],
        "verification": ["Verify current product behavior."],
        "readiness": "needs_verification",
    }


def test_calendar_month_horizon_and_empty_batches():
    assert end_date(date(2026, 8, 31), "6_months") == date(2027, 2, 28)
    assert end_date(date(2026, 9, 8), "2_weeks") == date(2026, 9, 22)
    plan = fixture_plan()
    assert plan["end_date"] == "2027-03-08"
    assert len(plan["batches"]) == 26
    assert all(not b["items"] for b in plan["batches"])
    validate_input_schema(INPUT_SCHEMA)


def test_all_model_fields_required():
    for schema in [MODEL_SCHEMA, *MODEL_SCHEMA["$defs"].values()]:
        if schema.get("type") == "object":
            assert set(schema["required"]) == set(schema["properties"])
            assert schema["additionalProperties"] is False


def test_future_edit_scope_and_prepared_item_protection():
    before = fixture_plan()
    after = deepcopy(before)
    after["batches"][1]["items"] = [item()]
    assert validate_change(before, after, editable={"week_02"}) == after
    with pytest.raises(ValueError, match="unselected"):
        validate_change(before, after, editable={"week_01"})
    with pytest.raises(ValueError, match="prepared item"):
        validate_change(before, after, editable={"week_02"}, reserved_items={"topic_1"})
    after["audit_run_id"] = str(uuid4())
    with pytest.raises(ValueError, match="audit_run_id"):
        validate_change(before, after, editable={"week_02"})


def test_duplicate_ids_invalid_calendar_and_untrusted_destinations():
    plan = fixture_plan()
    plan["batches"][0]["items"] = [item()]
    plan["batches"][1]["items"] = [item()]
    with pytest.raises(ValueError, match="unique"):
        ContentPlan.model_validate(plan)
    plan["batches"][1]["items"] = []
    plan["batches"][0]["items"][0]["destination"] = "https://evil.example/"
    with pytest.raises(ValueError, match="audited host"):
        ContentPlan.model_validate(plan)
    with pytest.raises(ValueError):
        parse_plan('{"bad":"plan"}')


def test_model_root_relative_destinations_resolve_without_mutating_receipted_result():
    original = fixture_plan()
    proposed = deepcopy(original)
    proposed["batches"][0]["items"] = [{**item(), "destination": "/seo-audit-workflows"}]
    normalized, changes = normalize_model_destinations(
        proposed, host=original["host"], editable={"week_01"}
    )
    assert proposed["batches"][0]["items"][0]["destination"] == "/seo-audit-workflows"
    assert normalized["batches"][0]["items"][0]["destination"] == (
        "https://example.com/seo-audit-workflows"
    )
    assert changes == [
        {
            "item_id": "topic_1",
            "from": "/seo-audit-workflows",
            "to": "https://example.com/seo-audit-workflows",
        }
    ]
    assert validate_change(original, normalized, editable={"week_01"}) == normalized
    # User files and frozen batches do not gain a permissive URL contract.
    with pytest.raises(ValueError, match="audited host"):
        ContentPlan.model_validate(proposed)
    unchanged, changes = normalize_model_destinations(proposed, host="example.com", editable=set())
    assert unchanged == proposed and not changes


@pytest.mark.parametrize(
    "destination",
    [
        "//evil.example/a",
        "/\\evil.example",
        "/a?x=1",
        "/a#fragment",
        "/a\n",
        "https://evil.example/a",
    ],
)
def test_model_destination_normalization_never_repairs_an_unsafe_or_offsite_url(destination):
    proposed = fixture_plan()
    proposed["batches"][0]["items"] = [{**item(), "destination": destination}]
    normalized, changes = normalize_model_destinations(
        proposed, host="example.com", editable={"week_01"}
    )
    assert normalized == proposed and not changes
    with pytest.raises(ValueError, match="audited host"):
        ContentPlan.model_validate(normalized)


def test_finite_schedule_never_rolls_the_horizon_forward():
    plan = fixture_plan()
    inputs = {key: plan[key] for key in ("audit_run_id", "keyword_run_id", "start_date")}
    inputs["duration"] = "2_weeks"
    schedule = WorkflowSchedule.model_validate(
        bound_schedule(
            inputs,
            {
                "cadence": "weekly",
                "weekdays": ["tuesday"],
                "local_time": "09:00",
                "timezone": "America/Los_Angeles",
            },
        )
    )
    assert next_run_after(schedule, datetime(2026, 9, 1, tzinfo=UTC)) == datetime(
        2026, 9, 8, 16, tzinfo=UTC
    )
    assert next_run_after(schedule, datetime(2026, 9, 21, tzinfo=UTC)) is None
    assert schedule.end_at.date() == date(2026, 9, 22)
