"""One email when a person's coding agent connects to Tin for the first time.

The terminal and the last browser tab after the OAuth login belong to the agent, so this is
the first surface Tin owns after the connection. It says the one sentence to tell the agent
and where the results land. Sent through Resend; off when no key is configured.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from tin_lite import analytics
from tin_lite.product_urls import dashboard_url

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
AGENT_PROMPT = "Use Tin to grow my project like a pro!"
SUBJECT = "Your agent is getting to work on your project"

_background: set[asyncio.Task[Any]] = set()


def _links(public_url: str) -> tuple[str, str]:
    base = public_url.rstrip("/")
    return f"{base}/system", f"{base}/decisions"


def welcome_html(public_url: str) -> str:
    my_system, decisions = _links(public_url)
    return (
        '<div style="font-family:Helvetica Neue,Arial,sans-serif;font-size:15px;'
        'line-height:22px;color:#26231c;">'
        "<p>Hey there,</p>"
        "<p>I'm Emre, one of Tin's co-founders. Your agent is getting to work on your "
        "project.</p>"
        "<p>Tin is in early beta, so you will hit rough edges. A small group of early builders "
        "is using it right now and telling me what is rough, and I would love for you to be one "
        "of them. I can give you free access for a while in exchange for hearing how it goes.</p>"
        "<p>What are you hoping Tin gets done for you first? If you have any feedback, hit reply "
        "and tell me. It comes straight to me.</p>"
        "<p>Emre</p>"
        f'<p style="color:#5f594c;font-size:13px;">Your project in Tin: <a href="{my_system}">'
        f'My system</a> (every workflow with its runs) · <a href="{decisions}">Decisions</a> '
        "(anything waiting for your yes).</p>"
        "</div>"
    )


def welcome_text(public_url: str) -> str:
    my_system, decisions = _links(public_url)
    return (
        "Hey there,\n\n"
        "I'm Emre, one of Tin's co-founders. Your agent is getting to work on your project.\n\n"
        "Tin is in early beta, so you will hit rough edges. A small group of early builders is "
        "using it right now and telling me what is rough, and I would love for you to be one of "
        "them. I can give you free access for a while in exchange for hearing how it goes.\n\n"
        "What are you hoping Tin gets done for you first? If you have any feedback, hit reply "
        "and tell me. It comes straight to me.\n\n"
        "Emre\n\n"
        f"Your project in Tin: My system ({my_system}), every workflow with its runs, and "
        f"Decisions ({decisions}), anything waiting for your yes.\n"
    )


async def send_welcome_email(
    *,
    settings: Any,
    auth: Any,
    clerk_user_id: str,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Send the welcome email; False when it is switched off or the address is unknown."""
    key = getattr(settings, "resend_api_key", None)
    if key is None:
        return False
    email = await auth.primary_email(clerk_user_id)
    if not email:
        logger.info("welcome email skipped: no email for %s", clerk_user_id)
        return False
    public_url = dashboard_url(settings)
    reply_to = getattr(settings, "welcome_email_reply_to", None)
    payload = {
        "from": settings.welcome_email_from,
        **({"reply_to": [reply_to]} if reply_to else {}),
        "to": [email],
        "subject": SUBJECT,
        "html": welcome_html(public_url),
        "text": welcome_text(public_url),
    }
    headers = {"Authorization": f"Bearer {key.get_secret_value()}"}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=15) as fresh:
                response = await fresh.post(RESEND_ENDPOINT, json=payload, headers=headers)
        else:
            response = await client.post(RESEND_ENDPOINT, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("welcome email failed for %s", clerk_user_id)
        analytics.capture(
            "welcome_email_failed",
            distinct_id=clerk_user_id,
            properties={"clerk_user_id": clerk_user_id},
        )
        return False
    analytics.capture(
        "welcome_email_sent",
        distinct_id=clerk_user_id,
        properties={"clerk_user_id": clerk_user_id},
    )
    return True


def send_in_background(*, settings: Any, auth: Any, clerk_user_id: str) -> None:
    """Fire the email without holding up the tool call that created the user."""
    if getattr(settings, "resend_api_key", None) is None:
        return
    task = asyncio.create_task(
        send_welcome_email(settings=settings, auth=auth, clerk_user_id=clerk_user_id)
    )
    _background.add(task)
    task.add_done_callback(_background.discard)
