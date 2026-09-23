"""Deterministic buyer-trust gate: validate pasted evidence, render PASS/FAIL.

No network, no model calls, no credentials. All evidence arrives as bounded
JSON-encoded strings so the package fits the closed community input contract.
Invalid evidence raises ValueError, which the runner records as a failed run.
"""

import json
from datetime import UTC, datetime


def _parse_object(raw, *, field, required_keys=(), optional_keys=()):
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{field} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    allowed = set(required_keys) | set(optional_keys)
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{field} has unsupported keys: {sorted(unknown)}")
    missing = [key for key in required_keys if key not in value]
    if missing:
        raise ValueError(f"{field} is missing keys: {missing}")
    return value


def _hsts_max_age(hsts):
    if not isinstance(hsts, str) or not hsts.strip():
        return None
    parts = [part.strip().lower() for part in hsts.split(";")]
    for part in parts:
        if part.startswith("max-age="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return None
    return None


def _row(signal, observed, ok):
    clipped = str(observed)[:80]
    result = "pass" if ok else "fix"
    return f"| {signal} | {clipped} | {result} |"


def run(ctx, inputs):
    headers = _parse_object(
        inputs["headers_json"],
        field="headers_json",
        optional_keys=(
            "hsts",
            "csp",
            "x_frame_options",
            "referrer_policy",
            "x_content_type_options",
            "security_txt_contact",
            "security_txt_expiry",
        ),
    )
    checks = _parse_object(
        inputs["checks_json"],
        field="checks_json",
        required_keys=(
            "privacy_status",
            "security_txt_status",
            "robots_status",
            "git_head_status",
            "env_status",
        ),
    )
    for key in (
        "privacy_status",
        "security_txt_status",
        "robots_status",
        "git_head_status",
        "env_status",
    ):
        if type(checks[key]) is not int or not 100 <= checks[key] <= 599:
            raise ValueError(f"checks_json.{key} must be an HTTP status code")

    raw_checkout = inputs.get("checkout_json") or ""
    if raw_checkout.strip():
        checkout = _parse_object(
            raw_checkout,
            field="checkout_json",
            optional_keys=("guest_option", "total_before_pay", "contact_url", "refund_url"),
        )
        for key in ("guest_option", "total_before_pay"):
            if key in checkout and type(checkout[key]) is not bool:
                raise ValueError(f"checkout_json.{key} must be a boolean")
        for key in ("contact_url", "refund_url"):
            if key in checkout:
                value = checkout[key]
                if not isinstance(value, str) or len(value) > 500:
                    raise ValueError(f"checkout_json.{key} must be a short string")
                if value and not value.startswith("https://"):
                    raise ValueError(f"checkout_json.{key} must be an https:// URL")
    else:
        checkout = {}

    fix_now = []
    fix_week = []
    roadmap = []
    evidence_rows = []

    max_age = _hsts_max_age(headers.get("hsts", ""))
    if max_age is None or max_age < 31536000:
        fix_now.append(
            "Strict-Transport-Security: set `max-age=31536000; includeSubDomains` "
            "at the host or reverse proxy."
        )
        hsts_verdict = "fix"
    else:
        hsts_verdict = "pass"
    evidence_rows.append(
        _row("Strict-Transport-Security", headers.get("hsts", ""), hsts_verdict == "pass")
    )

    csp = headers.get("csp", "")
    if not isinstance(csp, str) or "frame-ancestors" not in csp.lower():
        fix_week.append(
            "Content-Security-Policy: add `frame-ancestors 'none'` and tighten "
            "`script-src`/`connect-src` to hosts the site actually uses."
        )
        csp_verdict = "fix"
    else:
        csp_verdict = "pass"
    evidence_rows.append(_row("Content-Security-Policy", csp, csp_verdict == "pass"))

    for header_key, label in (
        ("x_frame_options", "X-Frame-Options"),
        ("x_content_type_options", "X-Content-Type-Options"),
        ("referrer_policy", "Referrer-Policy"),
    ):
        raw_value = headers.get(header_key, "")
        present = isinstance(raw_value, str) and bool(raw_value.strip())
        evidence_rows.append(_row(label, raw_value, present))
        if not present:
            fix_week.append(f"{label}: emit a site-wide value (see buyer-trust playbook).")

    if checks["git_head_status"] != 404 or checks["env_status"] != 404:
        fix_now.append(
            "Exposed repository or env path: `/.git/HEAD` and `/.env` must return 404. "
            "If either returns 200, rotate any exposed secret out of band."
        )
    evidence_rows.append(
        _row("/.git/HEAD status", checks["git_head_status"], checks["git_head_status"] == 404)
    )
    evidence_rows.append(_row("/.env status", checks["env_status"], checks["env_status"] == 404))

    if checks["security_txt_status"] != 200 or not headers.get("security_txt_contact"):
        fix_week.append("security.txt: serve `/.well-known/security.txt` with `Contact:`.")
    evidence_rows.append(
        _row(
            "security.txt status",
            checks["security_txt_status"],
            checks["security_txt_status"] == 200,
        )
    )

    robots_status = checks["robots_status"]
    robots_ok = robots_status < 500
    if not robots_ok:
        fix_week.append("robots.txt: resolve the 5xx so crawlers receive a stable result.")
    evidence_rows.append(_row("/robots.txt status", robots_status, robots_ok))

    expiry_raw = headers.get("security_txt_expiry", "")
    expiry_ok = False
    if expiry_raw:
        try:
            expires_at = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
            now = datetime.now(UTC)
            if expires_at <= now:
                fix_week.append("security.txt: renew the past `Expires:` date.")
            else:
                expiry_ok = True
        except ValueError as exc:
            raise ValueError("headers_json.security_txt_expiry must be ISO-8601") from exc
    elif checks["security_txt_status"] == 200:
        fix_week.append("security.txt: add a future `Expires:` date.")
    evidence_rows.append(_row("security.txt Expires", expiry_raw, expiry_ok))

    if checks["privacy_status"] != 200:
        fix_now.append("Footer links Privacy plus Terms on every page, including checkout.")
    evidence_rows.append(
        _row("/privacy status", checks["privacy_status"], checks["privacy_status"] == 200)
    )

    if checkout.get("total_before_pay") is False:
        fix_now.append("Checkout shows a line-item total before pay, without mixed content.")
    if checkout.get("guest_option") is False:
        roadmap.append("Checkout offers a guest option alongside any account creation.")
    if checkout and not checkout.get("contact_url"):
        fix_week.append("Contact page or footer with a real address or monitored inbox.")
    if checkout and not checkout.get("refund_url"):
        fix_week.append("Refunds or returns statement linked within one click of checkout.")

    verdict = "PASS" if not fix_now else "FAIL"
    lines = [
        "# Trust gate",
        "",
        f"Verdict: {verdict}",
        "",
        "## Evidence",
        "",
        "| Signal | Observed | Result |",
        "| --- | --- | --- |",
        *evidence_rows,
        "",
        "## Fix now",
        "",
        *([f"- {item}" for item in fix_now] or ["- None."]),
        "",
        "## Fix this week",
        "",
        *([f"- {item}" for item in fix_week] or ["- None."]),
        "",
        "## Roadmap",
        "",
        *([f"- {item}" for item in roadmap] or ["- None."]),
        "",
        "## Verification record",
        "",
        "Re-run with the same headers_json, checks_json and checkout_json inputs. "
        "This gate performs no fetching; reproduce the evidence with safe public GETs "
        "and compare byte-for-byte before changing headers or site copy.",
        "",
    ]
    content = "\n".join(lines)
    if len(content.encode("utf-8")) > 8000:
        raise ValueError("Trust-gate report exceeds its 8000-byte bound")
    return {"path": "reports/TRUST_GATE.md", "content": content}
