"""Project-authorized qualification over immutable files, outputs and ledger facts."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from tin_lite.billing import BillingService
from tin_lite.billing_contracts import digest, object_value
from tin_lite.private_workflows import PrivateWorkflowError, PrivateWorkflows
from tin_lite.publication import read_run_output
from tin_lite.run_usage import read_run_usage
from tin_lite.workflow_inputs import normalize_workflow_inputs
from tin_lite.workflow_packages import decode_workflow_source, package_digest, relative_path
from tin_lite.workflow_qualification import (
    Closed,
    Qualification,
    add_evidence,
    assess_output,
    check_package,
    content_digest,
    inspect_candidate,
    qualification_path,
    read_json,
)


class QualificationError(ValueError):
    """A fixed, safe diagnostic from qualification (never author source or provider text)."""


class RunCase(Closed):
    case_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")]
    run_id: UUID = Field(strict=False)


class QualificationSelection(Closed):
    path: str = Field(pattern=r"^workflow_packages/[a-z][a-z0-9_.-]{0,79}/workflow\.json$")
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    runs: list[RunCase] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def unique_runs(self):
        if len({r.run_id for r in self.runs}) != len(self.runs):
            raise ValueError("a run can be counted only once")
        return self


class CandidateSelection(Closed):
    run_id: UUID = Field(strict=False)


class EvaluationStart(QualificationSelection):
    workflow_id: UUID = Field(strict=False)
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    request_id: UUID = Field(strict=False)
    maximum_usd: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,2})?$")

    @model_validator(mode="after")
    def no_prior_runs(self):
        if self.runs:
            raise ValueError("start one case without supplied run evidence")
        return self


class WorkflowQualification(PrivateWorkflows):
    async def start_case(self, *, runtime, project_id, actor, client_id, selection):
        """An explicit member request, through ordinary admission; never a sandbox tool."""
        from tin_lite.run_service import start_workflow_run
        from tin_lite.workflow_definitions import resolve_execution_contract

        project = await self.project(project_id, actor)
        # Re-read the exact case file; the caller cannot substitute cheaper inputs at admission.
        definition, files = await self._files(
            repo_id=project.state_repo_id, revision=selection.revision, path=selection.path
        )
        raw = await self.storage.read_workflow_resource(
            repo_id=project.state_repo_id,
            commit_sha=selection.revision,
            path=qualification_path(definition["key"]),
        )
        contract = Qualification.model_validate(read_json(raw))
        checked = await check_package(files, selection.path, contract)
        case = next((c for c in contract.cases if c.id == selection.case_id), None)
        if case is None:
            raise QualificationError("Unknown evaluation case.")
        workflow = await self.db.get_workflow(selection.workflow_id)
        if workflow is None or workflow.project_id not in (None, project_id):
            raise LookupError("workflow not found")
        # An acknowledged or uncertain start keeps its original version and request identity.
        start_key = f"qualification:{selection.request_id}"
        existing = await self.db.get_run_by_start_key(
            project_id=project_id, start_idempotency_key=start_key
        )
        workflow = await resolve_execution_contract(
            storage=self.storage,
            workflow=workflow,
            project_id=project_id,
            revision=existing.definition_commit_sha if existing else workflow.current_commit_sha,
        )
        _, executable = await self._files(
            repo_id=workflow.definition_repo_id,
            revision=workflow.current_commit_sha,
            path=workflow.definition_path,
        )
        if (
            package_digest(executable, definition_path=workflow.definition_path)
            != checked["package_digest"]
        ):
            raise QualificationError("Activate the exact reviewed candidate before evaluating it.")
        billing = BillingService(database=self.db, settings=self.settings)
        normalized = normalize_workflow_inputs(
            schema=definition["input_schema"], project_id=project_id, inputs=case.inputs
        )
        terms = billing.terms(definition, project_id, normalized)
        ceiling = Decimal(terms["maximum_nanos"]) / 1_000_000_000
        if existing is not None:
            # Recovery observes the original authorization, including across price changes.
            maximum = await self.db.pool.fetchval(
                "SELECT maximum_nanos FROM billing_run_budgets WHERE run_id=$1", existing.id
            )
            if maximum is not None:
                ceiling = Decimal(maximum) / 1_000_000_000
        if ceiling > Decimal(selection.maximum_usd):
            raise QualificationError("Case ceiling exceeds the authorized evaluation maximum.")
        if ceiling and existing is None:
            if not getattr(runtime.database, "billing", None):
                raise QualificationError("Paid evaluation requires enforced run budgets.")
            preview = await billing.quote(
                runtime=runtime,
                project_id=project_id,
                actor=actor,
                workflow_id=workflow.id,
                inputs=case.inputs,
                preview_only=True,
            )
            if not preview.get("enabled"):
                raise QualificationError(
                    "paid evaluation requires enrolled billing and enforced run budgets"
                )
        run = await start_workflow_run(
            runtime=runtime,
            settings=self.settings,
            workflow=workflow,
            project_id=project_id,
            started_by_clerk_user_id=actor,
            started_by_oauth_client_id=client_id,
            start_idempotency_key=start_key,
            input_payload=case.inputs,
            definition_commit_sha=workflow.current_commit_sha,
        )
        return {
            "run_id": str(run.id),
            "case_id": case.id,
            "status": run.status.value,
            "definition_revision": run.definition_commit_sha,
            "package_digest": checked["package_digest"],
            "qualification_digest": checked["qualification_digest"],
            "maximum_usd": str(ceiling),
        }

    async def candidate(self, *, project_id, actor, run_id):
        project = await self.project(project_id, actor)
        run = await self.db.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise LookupError("run not found")
        output = await read_run_output(storage=self.storage, run=run, repo_id=project.state_repo_id)
        result = await inspect_candidate(output.content)
        return {
            **result,
            "source": {"run_id": str(run.id), "revision": output.revision, "path": output.path},
            "next_step": (
                "Review the proposed changes, then use the normal project-file "
                "commit and explicit activation or contribution flow."
            ),
        }

    async def _files(self, *, repo_id, revision, path):
        relative_path(path)
        raw = await self.storage.read_workflow_resource(
            repo_id=repo_id, commit_sha=revision, path=path
        )
        source = decode_workflow_source(raw, definition_path=path)
        files = {path: raw}
        for resource in source.resource_paths.values():
            files[resource] = await self.storage.read_workflow_resource(
                repo_id=repo_id, commit_sha=revision, path=resource
            )
        return source.definition, files

    async def qualify(self, *, project_id, actor, selection):
        project = await self.project(project_id, actor)
        definition, files = await self._files(
            repo_id=project.state_repo_id, revision=selection.revision, path=selection.path
        )
        case_path = qualification_path(definition["key"])
        raw = await self.storage.read_workflow_resource(
            repo_id=project.state_repo_id, commit_sha=selection.revision, path=case_path
        )
        contract = Qualification.model_validate(read_json(raw))
        report = await check_package(files, selection.path, contract)
        report["source"] = {
            "revision": selection.revision,
            "path": selection.path,
            "qualification_path": case_path,
        }
        cases = {case.id: case for case in contract.cases}
        samples = []
        for reference in selection.runs:
            if reference.case_id not in cases:
                raise QualificationError("Run reference names an unknown case.")
            run = await self.db.get_run(reference.run_id)
            # Authorize before reading another run's source, artifact or usage.
            if run is None or run.project_id != project_id:
                raise LookupError("run not found")
            if run.status.value not in {"succeeded", "failed", "stopped", "superseded"}:
                raise QualificationError("Qualification needs a finished run.")
            workflow = await self.db.get_workflow(run.workflow_id)
            if (
                workflow is None
                or workflow.project_id not in (None, project_id)
                or not run.definition_commit_sha
            ):
                raise LookupError("workflow not found")
            _, pinned_files = await self._files(
                repo_id=workflow.definition_repo_id,
                revision=run.definition_commit_sha,
                path=workflow.definition_path,
            )
            if (
                package_digest(pinned_files, definition_path=workflow.definition_path)
                != report["package_digest"]
            ):
                raise QualificationError("Run did not execute this exact candidate package.")
            case = cases[reference.case_id]
            expected = normalize_workflow_inputs(
                schema=definition["input_schema"], project_id=project_id, inputs=case.inputs
            )
            if (run.input or {}) != expected:
                raise QualificationError("Run inputs differ from the pinned case inputs.")
            output = None
            if run.canonical_commit_sha and run.artifact_path:
                output = await read_run_output(
                    storage=self.storage, run=run, repo_id=project.state_repo_id
                )
            usage = await read_run_usage(database=self.db, run=run)
            cost = await self._cost(
                run, usage, model_free=report["cost"]["basis"] == "computed_zero"
            )
            samples.append(
                {
                    "case_id": case.id,
                    "run_id": str(run.id),
                    "definition_revision": run.definition_commit_sha,
                    "inputs_digest": digest(run.input or {}),
                    "input_bytes": len(json.dumps(run.input or {}, sort_keys=True).encode()),
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "status": run.status.value,
                    "artifact": {
                        "revision": output.revision,
                        "path": output.path,
                        "bytes": len(output.content),
                        "sha256": content_digest(output.content),
                    }
                    if output
                    else None,
                    "assessment": assess_output(
                        case, status=run.status.value, content=output.content if output else None
                    ),
                    "usage": usage["own"],
                    **cost,
                }
            )
        return add_evidence(report, contract, samples)

    async def _cost(self, run, usage, *, model_free):
        async with (
            self.db.pool.acquire() as conn,
            conn.transaction(isolation="repeatable_read", readonly=True),
        ):
            budget = await conn.fetchrow(
                (
                    "SELECT terms, maximum_nanos, charged_nanos, status, "
                    "root_run_id FROM billing_run_budgets WHERE run_id=$1"
                ),
                run.id,
            )
            operations = await conn.fetch(
                (
                    "SELECT kind, status, observed_nanos, observation FROM "
                    "billing_operations WHERE run_id=$1 ORDER BY id"
                ),
                run.id,
            )
        terms = object_value(budget["terms"]) if budget else {}
        observations = usage["own"]["observations"]
        models = [
            o
            for o in observations
            if o["kind"]
            in {"native_model_service", "codex_openai_api", "codex_chatgpt_oauth", "unknown"}
        ]
        priced = [op for op in operations if op["kind"] in {"native_model", "codex_api"}]
        complete = (
            bool(budget)
            and (bool(models) or model_free)
            and len(priced) == len(models)
            and not usage["own"]["truncated"]
            and all(
                op["status"] == "observed" and op["observed_nanos"] is not None for op in priced
            )
            and all(o["outcome"] in {"response_received", "invalid_output"} for o in models)
        )
        amount = (
            sum(
                op["observed_nanos"]
                + object_value(op["observation"]).get("overage_absorbed_nanos", 0)
                for op in priced
            )
            if complete
            else 0
            if model_free and not models and not priced and not usage["own"]["truncated"]
            else None
        )

        def dollars(n):
            return str(Decimal(n) / 1_000_000_000) if n is not None else None

        return {
            "model_cost_usd": dollars(amount),
            "pricing_digest": digest(
                {
                    "terms": {
                        key: terms.get(key)
                        for key in ("rate_card", "pricing", "service_pricing", "codex_contract")
                    },
                    "models": sorted({(m["provider"], m["model"]) for m in models}, key=str),
                }
            ),
            "rate_card": terms.get("rate_card"),
            "enforced_ceiling_usd": dollars(budget["maximum_nanos"]) if budget else None,
            "actual_charge_usd": dollars(budget["charged_nanos"])
            if budget and budget["root_run_id"] == run.id and budget["status"] == "settled"
            else None,
            "settlement_status": budget["status"] if budget else "not_enrolled",
            "cost_evidence": "verified_ledger_usage"
            if complete
            else "computed_zero"
            if amount == 0
            else "unavailable",
        }


async def qualification_result(call):
    """Fixed diagnostics keep Pydantic's input echo out of API and MCP responses."""
    from tin_lite.billing_contracts import BillingError
    from tin_lite.integrations import IntegrationError
    from tin_lite.run_service import TemporalStartError, WorkflowExecutorUnavailableError
    from tin_lite.workflow_prerequisites import PrerequisiteError

    try:
        return await call
    except PrivateWorkflowError:
        raise
    except QualificationError as exc:
        raise PrivateWorkflowError("invalid_qualification", str(exc)) from exc
    except (BillingError, PrerequisiteError) as exc:
        raise PrivateWorkflowError(exc.code, str(exc), status=exc.status) from exc
    except TemporalStartError as exc:
        raise PrivateWorkflowError(
            "evaluation_start_unconfirmed",
            f"Run {exc.run_id}: retry the same evaluation request ID to recover its start.",
            status=502,
        ) from exc
    except (IntegrationError, WorkflowExecutorUnavailableError) as exc:
        raise PrivateWorkflowError(
            "evaluation_unavailable",
            "Check workflow runtime and integration prerequisites.",
            status=409,
        ) from exc
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise PrivateWorkflowError(
            "invalid_qualification",
            "The candidate, cases or run evidence do not match the qualification contract.",
        ) from exc
