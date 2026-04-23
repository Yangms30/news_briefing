"""Dispatch the user's latest category reports across all configured channels."""
from __future__ import annotations
import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from models import Report, SendLog, Setting, User

from .email_sender import EmailSender
from .slack import SlackSender
from .web import WebSender

logger = logging.getLogger(__name__)


@dataclass
class ChannelResult:
    channel: str
    status: str  # "success" | "failed" | "skipped"
    error_msg: str | None = None


def _active_channels(channels: dict) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    web = channels.get("web")
    if web is True or (isinstance(web, dict) and web.get("enabled")) or web == "true":
        out.append(("web", True))

    # Slack: bot-token mode (audio-capable) wins over webhook when both are
    # present. Bot mode requires BOTH slack_bot_token AND slack_channel_id.
    bot_token = channels.get("slack_bot_token")
    channel_id = channels.get("slack_channel_id")
    if (
        isinstance(bot_token, str)
        and bot_token.startswith("xoxb-")
        and isinstance(channel_id, str)
        and channel_id.strip()
    ):
        out.append((
            "slack",
            {"mode": "bot", "token": bot_token, "channel_id": channel_id.strip()},
        ))
    else:
        slack_webhook = channels.get("slack")
        if isinstance(slack_webhook, str) and slack_webhook.startswith("http"):
            out.append(("slack", {"mode": "webhook", "url": slack_webhook}))

    email = channels.get("email")
    if isinstance(email, str) and "@" in email:
        out.append(("email", email))
    return out


def _latest_reports_per_category(
    db: Session, user_id: int, categories: list[str]
) -> list[Report]:
    """Latest report per category, scoped to the user's currently-selected
    categories. If the user deselects a category in Settings, its past
    reports stay in the DB for history views but are excluded from dispatch.
    """
    if not categories:
        return []
    allowed = set(categories)
    rows = (
        db.query(Report)
        .filter(Report.user_id == user_id)
        .filter(Report.category.in_(allowed))
        .order_by(Report.created_at.desc())
        .all()
    )
    seen: set[str] = set()
    latest: list[Report] = []
    for r in rows:
        if r.category in seen:
            continue
        seen.add(r.category)
        latest.append(r)
    return latest


def dispatch_user_reports(db: Session, user_id: int) -> list[ChannelResult]:
    """Send the user's latest per-category reports through all active channels."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"user_id={user_id} not found")
    setting = db.query(Setting).filter(Setting.user_id == user_id).first()
    if not setting:
        raise ValueError(f"no settings for user_id={user_id}")
    try:
        channels = json.loads(setting.channels) if setting.channels else {}
    except json.JSONDecodeError:
        channels = {}

    # Honor the user's *current* category selection — past reports for
    # categories they've since removed from Settings must not be re-sent.
    try:
        categories: list[str] = json.loads(setting.categories or "[]")
    except json.JSONDecodeError:
        categories = []
    if not categories:
        logger.info("user_id=%s: no categories configured, skipping dispatch", user_id)
        return []

    reports = _latest_reports_per_category(db, user_id, categories)
    if not reports:
        logger.info("user_id=%s: no reports to dispatch", user_id)
        return []

    active = _active_channels(channels)
    if not active:
        logger.info("user_id=%s: no active channels", user_id)
        return []

    dispatch_id = uuid.uuid4().hex
    report_ids_json = json.dumps([r.id for r in reports])

    # Honor the user's TTS engine preference end-to-end so the audio
    # attached to email + slack matches the engine they'd hear on the
    # dashboard radio player. Falls back to auto-select when unset.
    tts_engine = channels.get("tts_engine") if isinstance(channels, dict) else None
    if tts_engine not in ("elevenlabs", "openai"):
        tts_engine = None

    results: list[ChannelResult] = []
    for name, target in active:
        if name == "web":
            status, err = WebSender.send(reports)
            recipient: str | None = "web"
        elif name == "slack":
            status, err = SlackSender.send(target, user.name, reports, tts_engine=tts_engine)
            # Snapshot recipient: channel_id for bot mode, webhook URL for webhook.
            if isinstance(target, dict):
                if target.get("mode") == "bot":
                    recipient = f"#{target.get('channel_id')}"
                else:
                    recipient = str(target.get("url", ""))
            else:
                recipient = str(target)
        elif name == "email":
            status, err = EmailSender.send(str(target), user.name, reports, tts_engine=tts_engine)
            recipient = str(target)
        else:
            continue
        db.add(SendLog(
            user_id=user_id,
            dispatch_id=dispatch_id,
            channel=name,
            status=status,
            error_msg=err,
            recipient=recipient,
            report_ids=report_ids_json,
        ))
        results.append(ChannelResult(channel=name, status=status, error_msg=err))
    db.commit()
    return results
