"""Receive-only SMS for Tin test identities.

Twilio posts every message sent to the Tin-owned test number here. The handler verifies
Twilio's request signature against the configured webhook URL, stores the message, and answers
with an empty TwiML document so nothing is ever sent back. Runs read the inbox through the
`search_sms` run tool; no code path sends SMS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Request, Response, status

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

router = APIRouter()


def twilio_signature(*, url: str, params: Mapping[str, str], auth_token: str) -> str:
    """Twilio's request signature: HMAC-SHA1 over the URL plus sorted form fields."""
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def twilio_signature_valid(
    *, url: str, params: Mapping[str, str], auth_token: str, signature: str
) -> bool:
    expected = twilio_signature(url=url, params=params, auth_token=auth_token)
    return hmac.compare_digest(expected, signature or "")


@router.post("/webhooks/twilio/sms")
async def twilio_inbound_sms(request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.test_phone_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    form = await request.form()
    params = {key: str(value) for key, value in form.multi_items() if isinstance(value, str)}
    urls = [settings.twilio_webhook_url]
    legacy = getattr(settings, "legacy_public_url", None)
    if legacy and not getattr(settings, "twilio_webhook_url_raw", None):
        # Accept signed deliveries already queued at the old configured origin.
        # Never derive a verification URL from an untrusted Host/Forwarded header.
        urls.append(f"{legacy.rstrip('/')}/webhooks/twilio/sms")
    if not any(
        twilio_signature_valid(
            url=url,
            params=params,
            auth_token=settings.twilio_auth_token.get_secret_value(),
            signature=request.headers.get("X-Twilio-Signature", ""),
        )
        for url in urls
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad signature")
    message_sid = params.get("MessageSid") or params.get("SmsSid") or ""
    to_number = params.get("To", "")
    if message_sid and to_number == settings.test_phone_number:
        await request.app.state.runtime.database.record_test_identity_sms(
            message_sid=message_sid,
            to_number=to_number,
            from_number=params.get("From", "unknown") or "unknown",
            body=params.get("Body", ""),
        )
    return Response(content=EMPTY_TWIML, media_type="text/xml")
