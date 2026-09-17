from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import time
from email.message import EmailMessage
from email.utils import formataddr
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tin_lite.procedures import EMAIL_SHORTLIST_HEADERS

MAX_CAMPAIGN_RECIPIENTS = 200


@dataclass(frozen=True)
class EmailSendPolicy:
    daily_send_cap: int
    send_interval_seconds: int
    window_start: time
    window_end: time
    timezone: str


@dataclass(frozen=True)
class CampaignRecipient:
    id: UUID
    candidate_id: str
    email: str
    name: str
    subject: str
    body: str
    follow_up_body: str | None


def campaign_plan_path(run_id: UUID | str) -> str:
    return f"outreach/email/campaigns/{run_id}/PLAN.md"


def campaign_revision_path(run_id: UUID | str, revision_id: UUID | str) -> str:
    return f"outreach/email/campaigns/{run_id}/revisions/{revision_id}.md"


def campaign_message_id(execution_key: str) -> str:
    return f"<tin.{hashlib.sha256(execution_key.encode()).hexdigest()[:40]}@tin.computer>"


def parse_email_send_policy(
    *,
    daily_send_cap: int,
    send_interval_seconds: int,
    send_window_start: str,
    send_window_end: str,
    send_timezone: str,
) -> EmailSendPolicy:
    if not 1 <= daily_send_cap <= MAX_CAMPAIGN_RECIPIENTS:
        raise ValueError("daily email send cap must be between 1 and 200")
    if not 1 <= send_interval_seconds <= 3600:
        raise ValueError("email send interval must be between 1 and 3600 seconds")
    try:
        window_start = time.fromisoformat(send_window_start)
        window_end = time.fromisoformat(send_window_end)
    except ValueError as exc:
        raise ValueError("email send window must use HH:MM") from exc
    if (
        window_start.second
        or window_start.microsecond
        or window_end.second
        or window_end.microsecond
    ):
        raise ValueError("email send window must use minute precision")
    if window_start >= window_end:
        raise ValueError("email send window must start before it ends")
    try:
        ZoneInfo(send_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("email send timezone must be an IANA timezone name") from exc
    return EmailSendPolicy(
        daily_send_cap=daily_send_cap,
        send_interval_seconds=send_interval_seconds,
        window_start=window_start,
        window_end=window_end,
        timezone=send_timezone,
    )


def parse_selected_shortlist(
    content: bytes,
    *,
    run_id: UUID,
    subject: str,
    body: str,
    follow_up_body: str | None,
) -> tuple[CampaignRecipient, ...]:
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != EMAIL_SHORTLIST_HEADERS:
        raise ValueError("email shortlist CSV has incorrect headers")
    recipients: list[CampaignRecipient] = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("email shortlist CSV has an invalid row shape")
        normalized = {key: str(value).strip() for key, value in row.items()}
        if normalized["status"] != "selected":
            continue
        address = normalized["email"].casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address):
            raise ValueError("selected shortlist row has an invalid email address")
        candidate_id = normalized["candidate_id"]
        if not candidate_id:
            raise ValueError("selected shortlist row has no candidate ID")
        name = normalized["name"]
        _validate_single_line(candidate_id, field="candidate ID")
        _validate_single_line(name, field="recipient name")
        rendered_subject = render_email_template(subject, name=name)
        _validate_single_line(rendered_subject, field="subject")
        recipients.append(
            CampaignRecipient(
                id=uuid5(run_id, f"recipient:{candidate_id}:{address}"),
                candidate_id=candidate_id,
                email=address,
                name=name,
                subject=rendered_subject,
                body=render_email_template(body, name=name),
                follow_up_body=(
                    render_email_template(follow_up_body, name=name) if follow_up_body else None
                ),
            )
        )
    if not recipients:
        raise ValueError("email shortlist has no selected recipients")
    if len(recipients) > MAX_CAMPAIGN_RECIPIENTS:
        raise ValueError(f"email campaign exceeds {MAX_CAMPAIGN_RECIPIENTS} recipients")
    if len({item.email for item in recipients}) != len(recipients):
        raise ValueError("email campaign contains duplicate recipients")
    return tuple(recipients)


def build_campaign_plan(
    *,
    run_id: UUID,
    shortlist_path: str,
    shortlist_commit_sha: str,
    recipients: tuple[CampaignRecipient, ...],
    subject_template: str,
    body_template: str,
    follow_up_template: str | None,
    follow_up_delay_days: int | None,
    send_interval_seconds: int,
    daily_send_cap: int,
    send_window_start: str,
    send_window_end: str,
    send_timezone: str,
    sender_account: str,
) -> bytes:
    lines = [
        "# Email campaign review",
        "",
        "> Nothing has been sent. Approval authorizes only the exact recipient and copy "
        "snapshot below.",
        "",
        "## Campaign",
        "",
        f"- Run: `{run_id}`",
        f"- Shortlist: `{shortlist_path}` at `{shortlist_commit_sha}`",
        f"- Sender: {sender_account}",
        f"- Recipients: {len(recipients)}",
        f"- Pacing: at least {send_interval_seconds} second(s) between messages",
        f"- Daily cap: {daily_send_cap} messages from this connected account",
        f"- Send window: {send_window_start}–{send_window_end} {send_timezone}",
        "- Follow-up: "
        + (
            "none"
            if follow_up_delay_days is None
            else f"after {follow_up_delay_days} day(s) when no reply is found"
        ),
        "",
        "## Initial email",
        "",
        f"**Subject:** {subject_template}",
        "",
        body_template,
        "",
    ]
    if follow_up_template:
        lines.extend(["## Follow-up", "", follow_up_template, ""])
    lines.extend(["## Recipients", ""])
    for recipient in recipients:
        label = formataddr((recipient.name, recipient.email)) if recipient.name else recipient.email
        lines.append(f"- {label} — candidate `{recipient.candidate_id}`")
    lines.extend(
        [
            "",
            "## Approval boundary",
            "",
            "The pinned run input and shortlist revision deterministically render one exact "
            "message per recipient. The only supported personalization is replacing `{{name}}` "
            "with the name shown above. ",
            "",
            "Approval sends the initial messages through the connected Google Workspace account. "
            "A follow-up is sent only after the declared delay and only when Tin does not find a "
            "reply. "
            "Changing the shortlist or copy after this snapshot requires a new campaign run.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def build_campaign_revision_plan(
    *,
    run_id: UUID,
    revision_id: UUID,
    revision_number: int,
    previous_follow_up_body: str,
    follow_up_body: str,
    pending_recipient_count: int,
) -> bytes:
    return (
        "\n".join(
            [
                "# Email campaign revision",
                "",
                "> Remaining deliveries are paused. Messages already delivered cannot be "
                "changed or recalled.",
                "",
                "## Revision",
                "",
                f"- Campaign run: `{run_id}`",
                f"- Revision: `{revision_id}` (number {revision_number})",
                f"- Pending follow-ups affected: {pending_recipient_count}",
                "- Initial emails affected: none",
                "",
                "## Proposed follow-up",
                "",
                follow_up_body,
                "",
                "## Previous follow-up",
                "",
                previous_follow_up_body,
                "",
                "## Approval boundary",
                "",
                "Approval applies this copy only to follow-ups that have not started. It does "
                "not send another initial email, alter a delivered message, or bypass reply "
                "suppression. Discarding this revision resumes the previously approved copy.",
                "",
            ]
        )
    ).encode("utf-8")


def build_email_message(
    *,
    sender_email: str,
    recipient_email: str,
    recipient_name: str,
    subject: str,
    body: str,
    message_id: str,
    in_reply_to: str | None = None,
) -> EmailMessage:
    _validate_single_line(sender_email, field="sender email")
    _validate_single_line(recipient_email, field="recipient email")
    _validate_single_line(recipient_name, field="recipient name")
    _validate_single_line(subject, field="subject")
    _validate_single_line(message_id, field="message ID")
    if in_reply_to is not None:
        _validate_single_line(in_reply_to, field="reply message ID")
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = formataddr((recipient_name, recipient_email))
    message["Subject"] = subject
    message["Message-ID"] = message_id
    if in_reply_to is not None:
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
    message.set_content(body)
    return message


def render_email_template(value: str, *, name: str) -> str:
    rendered = value.replace("{{name}}", name)
    if "\x00" in rendered:
        raise ValueError("email copy contains an unsafe null byte")
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("email copy contains an unsupported template placeholder")
    if not rendered.strip():
        raise ValueError("email copy cannot be empty")
    return rendered.strip()


def _validate_single_line(value: str, *, field: str) -> None:
    if "\r" in value or "\n" in value or "\x00" in value:
        raise ValueError(f"email {field} must be a single safe line")
