"""Offline checks for the deterministic trust gate."""

import importlib.util
import json
import sys
from pathlib import Path

from tin_lite.workflow_code import validate_code_definition, validate_code_result

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "workflow_packages" / "reports.trust_gate"


def load(tmp_path=None):
    """Import a copy so no bytecode cache lands inside the contributed package."""
    source = (PACKAGE / "main.py").read_bytes()
    if tmp_path is not None:
        target = Path(tmp_path) / "main.py"
        target.write_bytes(source)
        location = str(target)
    else:
        location = str(PACKAGE / "main.py")
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("trust_gate", location)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    definition = json.loads((PACKAGE / "workflow.json").read_text())["definition"]
    return module, definition


def passing_inputs():
    return {
        "headers_json": json.dumps(
            {
                "hsts": "max-age=31536000; includeSubDomains",
                "csp": "default-src 'self'; frame-ancestors 'none'",
                "x_frame_options": "DENY",
                "referrer_policy": "strict-origin-when-cross-origin",
                "x_content_type_options": "nosniff",
                "security_txt_contact": "mailto:security@example.com",
                "security_txt_expiry": "2027-01-01T00:00:00Z",
            }
        ),
        "checks_json": json.dumps(
            {
                "privacy_status": 200,
                "security_txt_status": 200,
                "robots_status": 200,
                "git_head_status": 404,
                "env_status": 404,
            }
        ),
        "checkout_json": json.dumps(
            {
                "guest_option": True,
                "total_before_pay": True,
                "contact_url": "https://example.com/contact",
                "refund_url": "https://example.com/refunds",
            }
        ),
    }


def test_passing_evidence_renders_pass_and_validates(tmp_path):
    module, definition = load(tmp_path)
    spec = validate_code_definition(definition)
    result = module.run(None, passing_inputs())
    validate_code_result(json.dumps(result).encode(), spec)
    assert "Verdict: PASS" in result["content"]
    assert "Verification record" in result["content"]


def test_missing_hsts_fails_with_ranked_fix(tmp_path):
    module, _ = load(tmp_path)
    inputs = passing_inputs()
    payload = json.loads(inputs["headers_json"])
    del payload["hsts"]
    inputs["headers_json"] = json.dumps(payload)
    result = module.run(None, inputs)
    assert "Verdict: FAIL" in result["content"]
    assert "Strict-Transport-Security" in result["content"]


def test_exposed_git_path_is_fix_now(tmp_path):
    module, _ = load(tmp_path)
    inputs = passing_inputs()
    payload = json.loads(inputs["checks_json"])
    payload["git_head_status"] = 200
    inputs["checks_json"] = json.dumps(payload)
    result = module.run(None, inputs)
    assert "Verdict: FAIL" in result["content"]
    assert "/.git/HEAD" in result["content"]


def test_malformed_json_and_bad_status_are_rejected(tmp_path):
    module, _ = load(tmp_path)
    inputs = passing_inputs()
    inputs["headers_json"] = "not-json"
    try:
        module.run(None, inputs)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed headers_json must raise ValueError")
    inputs = passing_inputs()
    payload = json.loads(inputs["checks_json"])
    payload["privacy_status"] = "200"
    inputs["checks_json"] = json.dumps(payload)
    try:
        module.run(None, inputs)
    except ValueError:
        pass
    else:
        raise AssertionError("non-integer status must raise ValueError")
