"""Dispatch archive — read-only view over SendLog groups by dispatch_id.

Each "지금 리포트 받기" click produces one batch: multiple SendLog rows
(one per active channel) sharing the same dispatch_id. This router
collapses them back into per-batch summaries/details for the archive UI.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Article, Report, SendLog
from schemas import (
    ArticleOut,
    DispatchChannelOut,
    DispatchDetail,
    DispatchSummary,
    ReportOut,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_report_out(r: Report) -> ReportOut:
    return ReportOut(
        id=r.id,
        user_id=r.user_id,
        category=r.category,
        radio_script=r.radio_script,
        created_at=r.created_at,
        articles=[ArticleOut.model_validate(a) for a in r.articles],
    )


def _parse_report_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [int(x) for x in value if isinstance(x, int)]


@router.get("", response_model=list[DispatchSummary])
def list_dispatches(
    user_id: int = Query(...),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """Return dispatch batches for a user, newest first.

    Legacy rows with dispatch_id="" (created before this migration) are
    excluded so the archive only shows batches with full metadata.
    """
    logs = (
        db.query(SendLog)
        .filter(SendLog.user_id == user_id, SendLog.dispatch_id != "")
        .order_by(SendLog.sent_at.desc())
        .all()
    )

    grouped: dict[str, list[SendLog]] = defaultdict(list)
    for log in logs:
        grouped[log.dispatch_id].append(log)

    # Resolve categories via a single query per batch (n batches, usually small).
    summaries: list[DispatchSummary] = []
    for did, rows in grouped.items():
        rids = _parse_report_ids(rows[0].report_ids)
        if rids:
            reports = db.query(Report).filter(Report.id.in_(rids)).all()
            categories = sorted({r.category for r in reports})
        else:
            categories = []
        summaries.append(
            DispatchSummary(
                dispatch_id=did,
                sent_at=max(r.sent_at for r in rows),
                channels=[DispatchChannelOut.model_validate(r) for r in rows],
                report_count=len(rids),
                categories=categories,
            )
        )

    summaries.sort(key=lambda s: s.sent_at, reverse=True)
    return summaries[:limit]


@router.get("/{dispatch_id}", response_model=DispatchDetail)
def get_dispatch(dispatch_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(SendLog)
        .filter(SendLog.dispatch_id == dispatch_id)
        .order_by(SendLog.sent_at.asc())
        .all()
    )
    if not rows:
        raise HTTPException(404, "Dispatch not found")

    rids = _parse_report_ids(rows[0].report_ids)
    reports: list[Report] = []
    if rids:
        fetched = db.query(Report).filter(Report.id.in_(rids)).all()
        # Preserve original rids order so the UI shows reports as dispatched.
        order = {rid: idx for idx, rid in enumerate(rids)}
        fetched.sort(key=lambda r: order.get(r.id, len(order)))
        reports = fetched

    return DispatchDetail(
        dispatch_id=dispatch_id,
        sent_at=max(r.sent_at for r in rows),
        channels=[DispatchChannelOut.model_validate(r) for r in rows],
        reports=[_to_report_out(r) for r in reports],
    )
