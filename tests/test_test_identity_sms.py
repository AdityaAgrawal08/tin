from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tin_lite.domain import TEST_IDENTITY_SMS_CAPABILITY, TestIdentitySms
from tin_lite.sms import EMPTY_TWIML, router, twilio_signature, twilio_signature_valid

ROOT = Path(__file__).parents[1]
WEBHOOK_URL = "https://lite.test/webhooks/twilio/sms"
TOKEN = "twilio-auth-token"  # noqa: S105
NUMBER = "+15596662364"


def test_twilio_signature_matches_documented_scheme() -> None:
    # Twilio's documented example: URL plus sorted key/value pairs, HMAC-SHA1, base64.
    params = {"To": "+15551234567", "From": "+15559876543", "Body": "hi", "MessageSid": "SM1"}
    signature = twilio_signature(url=WEBHOOK_URL, params=params, auth_token=TOKEN)
    assert twilio_signature_valid(
        url=WEBHOOK_URL, params=params, auth_token=TOKEN, signature=signature
    )
    assert not twilio_signature_valid(
        url=WEBHOOK_URL, params={**params, "Body": "bye"}, auth_token=TOKEN, signature=signature
    )
    assert not twilio_signature_valid(
        url=WEBHOOK_URL, params=params, auth_token=TOKEN, signature=""
    )


class SmsDatabase:
    def __init__(self) -> None:
        self.recorded: list[dict] = []

    async def record_test_identity_sms(self, **values):
        self.recorded.append(values)
        return True


def _app(database: SmsDatabase, *, enabled: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        test_phone_enabled=enabled,
        twilio_webhook_url=WEBHOOK_URL,
        twilio_auth_token=SecretStr(TOKEN),
        test_phone_number=NUMBER,
    )
    app.state.runtime = SimpleNamespace(database=database)
    return app


@pytest.mark.asyncio
async def test_webhook_stores_only_signed_messages_to_the_tin_number() -> None:
    database = SmsDatabase()
    app = _app(database)
    params = {"MessageSid": "SM123", "To": NUMBER, "From": "+15550001111", "Body": "Code 482913"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://lite.test"
    ) as client:
        unsigned = await client.post("/webhooks/twilio/sms", data=params)
        assert unsigned.status_code == 403
        assert database.recorded == []

        signed = await client.post(
            "/webhooks/twilio/sms",
            data=params,
            headers={
                "X-Twilio-Signature": twilio_signature(
                    url=WEBHOOK_URL, params=params, auth_token=TOKEN
                )
            },
        )
        assert signed.status_code == 200
        assert signed.headers["content-type"].startswith("text/xml")
        assert signed.text == EMPTY_TWIML
        assert database.recorded == [
            {
                "message_sid": "SM123",
                "to_number": NUMBER,
                "from_number": "+15550001111",
                "body": "Code 482913",
            }
        ]

        other = {**params, "MessageSid": "SM124", "To": "+15550002222"}
        elsewhere = await client.post(
            "/webhooks/twilio/sms",
            data=other,
            headers={
                "X-Twilio-Signature": twilio_signature(
                    url=WEBHOOK_URL, params=other, auth_token=TOKEN
                )
            },
        )
        assert elsewhere.status_code == 200
        assert len(database.recorded) == 1


@pytest.mark.asyncio
async def test_webhook_is_absent_until_a_number_is_configured() -> None:
    app = _app(SmsDatabase(), enabled=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://lite.test"
    ) as client:
        assert (await client.post("/webhooks/twilio/sms", data={"To": NUMBER})).status_code == 404


@pytest.mark.asyncio
async def test_domain_transition_accepts_only_explicit_signed_origins():
    app = _app(SmsDatabase())
    app.state.settings.twilio_webhook_url = "https://app.test/webhooks/twilio/sms"
    app.state.settings.legacy_public_url = "https://lite.test"
    params = {"MessageSid": "SM123", "To": NUMBER, "Body": "test"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://app.test"
    ) as client:
        for origin, expected in (("app.test", 200), ("lite.test", 200), ("evil.test", 403)):
            response = await client.post(
                "/webhooks/twilio/sms",
                data=params,
                headers={
                    "Host": origin,
                    "X-Twilio-Signature": twilio_signature(
                        url=f"https://{origin}/webhooks/twilio/sms", params=params, auth_token=TOKEN
                    ),
                },
            )
            assert response.status_code == expected
        app.state.settings.legacy_public_url = None
        response = await client.post(
            "/webhooks/twilio/sms",
            data=params,
            headers={
                "X-Twilio-Signature": twilio_signature(
                    url=WEBHOOK_URL, params=params, auth_token=TOKEN
                ),
            },
        )
        assert response.status_code == 403


def test_sms_path_is_receive_only_and_bounded() -> None:
    source = (ROOT / "src" / "tin_lite" / "sms.py").read_text()
    run_tools = (ROOT / "src" / "tin_lite" / "run_tools.py").read_text()
    migration = (ROOT / "migrations" / "026_test_identity_sms.sql").read_text()
    assert "Messages.json" not in source and "messages.create" not in source
    assert "send" not in run_tools.split("async def search_sms")[1].split("host = urlsplit")[
        0
    ].lower().replace("sends from", "")
    assert TEST_IDENTITY_SMS_CAPABILITY == "test_identity.sms.read"
    assert "CREATE TABLE test_identity_sms_messages" in migration
    assert "message_sid text NOT NULL UNIQUE" in migration
    assert "ADD COLUMN phone_number" in migration
    activities = (ROOT / "src" / "tin_lite" / "activities.py").read_text()
    assert "TEST_IDENTITY_SMS_CAPABILITY" in activities
    assert (
        TestIdentitySms(
            id=uuid4(),
            message_sid="SM1",
            to_number=NUMBER,
            from_number="+1",
            body="x",
            received_at=datetime.now(UTC),
        ).body
        == "x"
    )
