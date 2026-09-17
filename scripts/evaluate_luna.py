from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from tin_lite.luna import LunaRouter, OpenAIResponsesClient, TinWorkflowApiClient
from tin_lite.settings import get_settings

ROOT = Path(__file__).parents[1]
DEFAULT_CORPUS = ROOT / "evals" / "luna_routing.jsonl"


def load_corpus(path: Path) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("evaluation case IDs must be unique")
    return cases


async def evaluate(*, project_id: UUID, corpus_path: Path) -> int:
    settings = get_settings()
    if settings.luna_api_key is None:
        raise SystemExit("TIN_LITE_LUNA_API_KEY is required to run the Luna evaluation")
    responses = OpenAIResponsesClient(
        api_key=settings.luna_api_key.get_secret_value(),
        model=settings.luna_model,
        base_url=settings.luna_base_url,
        timeout_seconds=settings.luna_timeout_seconds,
    )
    workflow_api = TinWorkflowApiClient(base_url=settings.switchboard_public_url)
    router = LunaRouter(responses)
    cases = load_corpus(corpus_path)
    failures: list[dict] = []
    try:
        workflows = await workflow_api.list_workflows(project_id)
        for case in cases:
            try:
                decision = await router.route(
                    workflows=workflows,
                    project_id=project_id,
                    message=case["prompt"],
                )
                actual_action = "start" if decision.tool_call is not None else "reply"
                asked_question = bool(decision.message and "?" in decision.message)
                expected_workflow_key = case.get("expected_workflow_key")
                correct_workflow = (
                    expected_workflow_key is None or decision.workflow_key == expected_workflow_key
                )
                passed = (
                    actual_action == case["expected_action"]
                    and (not case["expects_question"] or asked_question)
                    and correct_workflow
                )
                if not passed:
                    failures.append(
                        {
                            "id": case["id"],
                            "expected_action": case["expected_action"],
                            "actual_action": actual_action,
                            "expects_question": case["expects_question"],
                            "asked_question": asked_question,
                            "expected_workflow_key": expected_workflow_key,
                            "actual_workflow_key": decision.workflow_key,
                        }
                    )
            except Exception as exc:
                failures.append({"id": case["id"], "error": type(exc).__name__})
    finally:
        await responses.close()
        await workflow_api.close()
    print(
        json.dumps(
            {
                "model": settings.luna_model,
                "cases": len(cases),
                "passed": len(cases) - len(failures),
                "failed": len(failures),
                "failures": failures,
            },
            indent=2,
        )
    )
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Luna without executing workflows")
    parser.add_argument("--project-id", required=True, type=UUID)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(evaluate(project_id=args.project_id, corpus_path=args.corpus)))


if __name__ == "__main__":
    main()
