"""One fixed recipe, not executable category metadata or a user-authored graph."""

from datetime import date

from tin_lite.content_plan import DURATIONS
from tin_lite.organic_audit import MARKETS, public_site

KEY = "organic.traffic_system"
TECHNICAL_KEY = "organic.technical_fix"
LEGACY_STEPS = {
    "audit": "organic.audit",
    "keywords": "organic.keyword_plan",
    "technical": TECHNICAL_KEY,
    "content": "content.plan",
}
LEGACY_POLICY = {
    "version": "organic-traffic-v1",
    "steps": LEGACY_STEPS,
    "max_technical_findings": 1,
    "schedule": "manual_only",
}
STEPS = {**LEGACY_STEPS, "draft": "content.generate", "delivery": "content.deliver"}
POLICY = {**LEGACY_POLICY, "version": "organic-traffic-v2", "steps": STEPS}


def policy_steps(policy):
    if policy == LEGACY_POLICY:
        return LEGACY_STEPS
    if policy == POLICY:
        return STEPS
    raise ValueError("Unsupported organic system policy.")


INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "project_id": {"type": "string", "format": "uuid"},
        "site_url": {
            "type": "string",
            "title": "Public website",
            "format": "uri",
            "pattern": "^https://",
            "maxLength": 500,
        },
        "market": {"type": "string", "title": "Buyer market", "enum": list(MARKETS)},
        "buyer_context": {
            "type": "string",
            "title": "Product and buyers",
            "minLength": 20,
            "maxLength": 2000,
        },
        "start_date": {
            "type": "string",
            "title": "Content plan starts",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
        "duration": {
            "type": "string",
            "title": "Content plan duration",
            "enum": list(DURATIONS),
            "default": "6_months",
        },
        "keyword_max_cost_usd": {
            "type": "number",
            "title": "Keyword research limit (USD)",
            "minimum": 5,
            "maximum": 25,
            "default": 9,
        },
        "technical_fix": {
            "type": "boolean",
            "title": "Propose one technical fix",
            "default": False,
            "description": "May open one unmerged PR; repository CI may run.",
        },
        "content_delivery": {
            "type": "string",
            "title": "Article delivery",
            "enum": ["auto", "draft_only"],
            "default": "auto",
            "description": "With GitHub connected, open a PR after draft approval. "
            "Otherwise keep the Markdown draft in Tin. Nothing is merged or published.",
        },
        "expected_repository": {
            "type": "string",
            "title": "GitHub owner/repository",
            "default": "",
            "maxLength": 140,
        },
        "repository_serves_site": {
            "type": "boolean",
            "default": False,
            "title": "This repository serves the audited website",
        },
    },
    "required": ["project_id", "site_url", "market", "buyer_context", "start_date"],
}


def check_inputs(inputs):
    public_site(inputs["site_url"])
    date.fromisoformat(inputs["start_date"])
    if inputs["market"] not in MARKETS or inputs.get("duration", "6_months") not in DURATIONS:
        raise ValueError("Choose a supported market and content-plan duration.")
    if inputs.get("technical_fix") and (
        inputs.get("repository_serves_site") is not True or not inputs.get("expected_repository")
    ):
        raise ValueError("Confirm the exact GitHub repository before enabling technical fixes.")


async def system_facts(*, database, project_id, run_id):
    run = await database.get_run(run_id)
    if run is None or run.project_id != project_id or run.executor != KEY:
        raise LookupError("Organic traffic system run not found.")
    prepared = await database.get_effect(f"traffic:{run_id}:prepare")
    policy = (prepared.result or {}).get("policy") if prepared else None
    # Old receipts and old runs retain their four-step projection.
    selected_steps = policy_steps(
        policy or (POLICY if "content_delivery" in run.input else LEGACY_POLICY)
    )
    steps = []
    for step, key in selected_steps.items():
        receipt = await database.get_effect(f"traffic:{run_id}:step:{step}")
        value = receipt.result if receipt and receipt.status == "completed" else {}
        child = None
        if value.get("run_id"):
            from uuid import UUID

            child = await database.get_run(UUID(value["run_id"]))
            if child is None or child.project_id != project_id:
                raise ValueError("System child projection is unavailable.")
            if step == "draft":
                # A revision replaces the reviewable copy, not the program item. Follow
                # the same durable lineage used by Decisions, including while it runs.
                current = await database.pool.fetchval(
                    "SELECT id FROM workflow_runs WHERE project_id=$1 AND workflow_id=$2 "
                    "AND (id=$3 OR review_root_run_id=$3) "
                    "ORDER BY review_version DESC LIMIT 1",
                    project_id,
                    child.workflow_id,
                    child.id,
                )
                if current:
                    child = await database.get_run(current)
        steps.append(
            {
                "step": step,
                "workflow_key": key,
                "run_id": str(child.id) if child else None,
                "status": child.status.value if child else value.get("status", "not_started"),
                "reason": value.get("reason"),
                "artifact_path": child.artifact_path if child else None,
                "artifact_ref": child.artifact_ref if child else None,
                "canonical_commit_sha": child.canonical_commit_sha if child else None,
                "project_workflow_id": str(child.project_workflow_id)
                if child and child.project_workflow_id
                else None,
            }
        )
    return {
        "run_id": str(run.id),
        "project_id": str(project_id),
        "status": run.status.value,
        "steps": steps,
        "artifact_path": run.artifact_path,
        "artifact_ref": run.artifact_ref,
    }
