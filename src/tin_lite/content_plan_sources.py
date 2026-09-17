"""Resolve exact, receipt-verified research publications and bounded project context."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from tin_lite.keyword_plan import LIMITS as KEYWORD_LIMITS
from tin_lite.keyword_plan import paths as keyword_paths
from tin_lite.organic_audit import ARTIFACT_LIMITS, audit_hosts, audit_paths, digest
from tin_lite.project_files import safe_project_file_path


async def research_sources(*, database, storage, project, inputs):
    sources, loaded = {}, {}
    for kind, executor, prefix, source_paths, limits in (
        ("audit", "organic.audit", "organic", audit_paths, ARTIFACT_LIMITS),
        ("keyword", "organic.keyword_plan", "keyword", keyword_paths, KEYWORD_LIMITS),
    ):
        source = await database.get_run(UUID(inputs[f"{kind}_run_id"]))
        if (
            source is None
            or source.project_id != project.id
            or source.executor != executor
            or source.status.value != "succeeded"
            or not source.canonical_commit_sha
        ):
            raise ValueError(f"Choose a successful {kind} publication in this project.")
        receipt = await database.get_effect(f"{prefix}:{source.id}:publish")
        publication = receipt.result if receipt and receipt.status == "completed" else {}
        if publication.get("canonical_commit_sha") != source.canonical_commit_sha:
            raise ValueError(f"The {kind} publication receipt does not match its run.")
        documents = {}
        for name, path in source_paths(str(source.id)).items():
            content = await storage.read_canonical_artifact(
                repo_id=project.state_repo_id, commit_sha=source.canonical_commit_sha, path=path
            )
            if not 0 < len(content) <= limits[name]:
                raise ValueError(f"The {kind} source exceeds its read contract.")
            documents[path] = content.decode("utf-8")
        if digest(documents) != publication.get("documents_sha256"):
            raise ValueError(f"The {kind} bundle failed receipt verification.")
        loaded[kind] = {
            name: json.loads(documents[path])
            for name, path in source_paths(str(source.id)).items()
            if name.endswith(".json")
        }
        evidence = loaded[kind]["evidence.json"]
        if evidence.get("run_id") != str(source.id) or evidence.get("project_id") != str(
            project.id
        ):
            raise ValueError("Research evidence has a different owner or run.")
        identity = evidence if kind == "audit" else loaded[kind]["keywords.json"]
        if identity.get("definition_commit_sha") != source.definition_commit_sha:
            raise ValueError("The research definition differs from its pinned run.")
        sources[kind] = {
            "run_id": str(source.id),
            "revision": source.canonical_commit_sha,
            "documents_sha256": publication["documents_sha256"],
            "paths": source_paths(str(source.id)),
        }
    audit = loaded["audit"]["evidence.json"]
    keywords = loaded["keyword"]["keywords.json"]
    if (
        keywords["scope"]["host"] not in audit_hosts(audit["scope"])
        or audit["scope"]["market"] != keywords["scope"]["market"]
        or audit["scope"].get("language") != "en"
        or keywords["scope"].get("language") != "en"
    ):
        raise ValueError(
            "Audit and keywords must target the same host, market and English language."
        )
    if digest(keywords) != loaded["keyword"]["evidence.json"].get("inventory_sha256"):
        raise ValueError("Keyword inventory failed evidence verification.")
    findings = loaded["audit"]["findings.json"]
    if digest(audit) != findings.get("evidence_sha256"):
        raise ValueError("Audit findings failed evidence verification.")
    rows = []
    for finding in findings["findings"]:
        if finding.get("category") == "content":
            rows.append({"source_id": f"audit:{finding['id']}", "data": finding})
    for group in keywords["groups"]:
        rows.append({"source_id": f"group:{group['id']}", "data": group})
    # Keep every keyword (including exclusions) but compact repeated provider metadata.
    # The full original observations remain retrievable through the pinned source reference.
    for keyword in keywords["keywords"]:
        observations = keyword.get("observations", [])
        rows.append(
            {
                "source_id": f"keyword:{keyword['id']}",
                "data": {
                    "id": keyword["id"],
                    "keyword": keyword["keyword"],
                    "observations": [
                        {
                            key: row.get(key)
                            for key in (
                                "source_id",
                                "observed_at",
                                "search_volume",
                                "keyword_difficulty",
                                "ranking_url",
                                "position",
                                "clicks",
                                "impressions",
                            )
                        }
                        for row in observations[:2]
                    ],
                    "observations_omitted": keyword.get("observations_omitted", 0)
                    + max(0, len(observations) - 2),
                },
            }
        )
    return {
        "sources": sources,
        "scope": {
            key: keywords["scope"][key] for key in ("host", "market", "language", "buyer_context")
        },
        "rows": rows,
        "excluded": keywords["excluded"],
        "technical_findings_count": sum(
            finding.get("category") != "content" for finding in findings["findings"]
        ),
        "page_candidates": [
            {"url": page["url"], "title": page.get("title")}
            for page in audit.get("crawl", {}).get("pages", [])
        ],
        "limitations": [
            "Frozen research; no current page contents verified.",
            "Keyword group and exclusion judgments may be wrong.",
        ],
    }


async def context_files(*, storage, project, revision, paths):
    if len(paths) > 8 or len(set(paths)) != len(paths):
        raise ValueError("Choose at most eight distinct context files.")
    result = []
    total = 0
    for path in paths:
        if not safe_project_file_path(path):
            raise ValueError("Context file path is unsafe.")
        content = await storage.read_canonical_artifact(
            repo_id=project.state_repo_id, commit_sha=revision, path=path
        )
        total += len(content)
        if len(content) > 20_000 or total > 60_000:
            raise ValueError("Context files must be at most 20 KB each and 60 KB together.")
        result.append(
            {
                "source_id": f"file:{path}",
                "path": path,
                "revision": revision,
                "sha256": hashlib.sha256(content).hexdigest(),
                "content": content.decode("utf-8"),
            }
        )
    return result
