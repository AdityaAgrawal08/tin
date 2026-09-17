from types import SimpleNamespace
from uuid import uuid4

import pytest

from tin_lite.content_plan_sources import research_sources
from tin_lite.keyword_plan import paths as keyword_paths
from tin_lite.organic_audit import audit_paths, canonical_json, digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [None, "owner", "host", "market", "tamper", "definition", "verified_www", "unverified_www"],
)
async def test_research_identity_and_original_publication_hashes(fault):
    project = SimpleNamespace(id=uuid4(), state_repo_id="project/test")
    audit, keyword = uuid4(), uuid4()
    scope = {
        "host": "example.com",
        "market": "US",
        "language": "en",
        "buyer_context": "A real product",
    }
    runs = {
        audit: SimpleNamespace(
            id=audit,
            project_id=project.id,
            executor="organic.audit",
            status=SimpleNamespace(value="succeeded"),
            canonical_commit_sha="a" * 40,
            definition_commit_sha="d" * 40,
        ),
        keyword: SimpleNamespace(
            id=keyword,
            project_id=project.id,
            executor="organic.keyword_plan",
            status=SimpleNamespace(value="succeeded"),
            canonical_commit_sha="b" * 40,
            definition_commit_sha="d" * 40,
        ),
    }
    if fault == "owner":
        runs[keyword].project_id = uuid4()
    evidence = {
        "run_id": str(audit),
        "project_id": str(project.id),
        "definition_commit_sha": "d" * 40,
        "scope": scope,
        "crawl": {"pages": []},
    }
    inventory = {
        "run_id": str(keyword),
        "project_id": str(project.id),
        "definition_commit_sha": "d" * 40,
        "scope": {**scope},
        "keywords": [{"id": "k1", "keyword": "useful product query", "observations": []}],
        "groups": [],
        "excluded": [],
    }
    if fault == "host":
        inventory["scope"]["host"] = "other.example"
    if fault == "market":
        inventory["scope"]["market"] = "GB"
    if fault == "definition":
        inventory["definition_commit_sha"] = "e" * 40
    if fault in {"verified_www", "unverified_www"}:
        inventory["scope"]["host"] = "www.example.com"
        if fault == "verified_www":
            evidence["scope"] = {
                **scope,
                "url": "https://example.com/",
                "policy_version": "organic-audit-v5",
                "site_identity": {
                    "redirects": [
                        {
                            "from": "https://example.com/",
                            "to": "https://www.example.com/",
                            "status_code": 308,
                        }
                    ]
                },
            }
    bundles = {
        f"organic:{audit}:publish": {
            audit_paths(str(audit))["AUDIT.md"]: "# Audit",
            audit_paths(str(audit))["evidence.json"]: canonical_json(evidence).decode(),
            audit_paths(str(audit))["findings.json"]: canonical_json(
                {"evidence_sha256": digest(evidence), "findings": []}
            ).decode(),
        },
        f"keyword:{keyword}:publish": {
            keyword_paths(str(keyword))["PLAN.md"]: "# Keywords",
            keyword_paths(str(keyword))["keywords.json"]: canonical_json(inventory).decode(),
            keyword_paths(str(keyword))["evidence.json"]: canonical_json(
                {
                    "run_id": str(keyword),
                    "project_id": str(project.id),
                    "inventory_sha256": digest(inventory),
                }
            ).decode(),
        },
    }
    receipts = {
        key: SimpleNamespace(
            status="completed",
            result={
                "canonical_commit_sha": runs[
                    audit if key.startswith("organic:") else keyword
                ].canonical_commit_sha,
                "documents_sha256": digest(value),
            },
        )
        for key, value in bundles.items()
    }
    if fault == "tamper":
        bundles[f"keyword:{keyword}:publish"][keyword_paths(str(keyword))["PLAN.md"]] += " tampered"
    reads = []

    class Database:
        async def get_run(self, id):
            return runs[id]

        async def get_effect(self, key):
            return receipts[key]

    class Storage:
        async def read_canonical_artifact(self, *, repo_id, commit_sha, path):
            reads.append(commit_sha)
            assert repo_id == project.state_repo_id
            return next(bundle[path].encode() for bundle in bundles.values() if path in bundle)

    call = research_sources(
        database=Database(),
        storage=Storage(),
        project=project,
        inputs={"audit_run_id": str(audit), "keyword_run_id": str(keyword)},
    )
    if fault not in {None, "verified_www"}:
        with pytest.raises(ValueError):
            await call
    else:
        result = await call
        assert result["rows"][0]["source_id"] == "keyword:k1"
        assert set(reads) == {"a" * 40, "b" * 40}
