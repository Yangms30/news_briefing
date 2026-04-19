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
    slack = channels.get("slack")
    if isinstance(slack, str) and slack.startswith("http"):
        out.append(("slack", slack))
    email = channels.get("email")
    if isinstance(email, str) and "@" in email:
        out.append(("email", email))
    return out


def _latest_reports_per_category(db: Session, user_id: int) -> list[Report]:
    rows = (
        db.query(Report)
        .filter(Report.user_id == user_id)
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

    reports = _latest_reports_per_category(db, user_id)
    if not reports:
        logger.info("user_id=%s: no reports to dispatch", user_id)
        return []

    active = _active_channels(channels)
    if not active:
        logger.info("user_id=%s: no active channels", user_id)
        return []

    dispatch_id = uuid.uuid4().hex
    report_ids_json = json.dumps([r.id for r in reports])

    results: list[ChannelResult] = []
    for name, target in active:
        if name == "web":
            status, err = WebSender.send(reports)
            recipient: str | None = "web"
        elif name == "slack":
            status, err = SlackSender.send(str(target), user.name, reports)
            recipient = str(target)
        elif name == "email":
            status, err = EmailSender.send(str(target), user.name, reports)
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
