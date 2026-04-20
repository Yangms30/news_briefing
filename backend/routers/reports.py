import json
import logging
import queue
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import Article, Report, Setting
from pipeline.service import generate_reports_for_user
from schemas import ArticleOut, ReportGenerateResponse, ReportOut
from services.tts import TTSUnavailable, synthesize_to_file

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_out(r: Report) -> ReportOut:
    return ReportOut(
        id=r.id,
        user_id=r.user_id,
        category=r.category,
        radio_script=r.radio_script,
        created_at=r.created_at,
        articles=[ArticleOut.model_validate(a) for a in r.articles],
    )


@router.get("", response_model=list[ReportOut])
def list_reports(
    user_id: int = Query(...),
    category: str | None = Query(None),
    limit: int = Query(200, le=500),
    latest_only: bool = Query(True),
    db: Session = Depends(get_db),
):
    """List reports for this user, newest first.

    By default keeps only the latest report per category (existing dashboard
    "오늘" view). Pass `latest_only=false` to get every row — used by the new
    date-grouped dashboard layout where past days need all of their reports.
    """
    q = db.query(Report).filter(Report.user_id == user_id)
    if category and category != "전체":
        q = q.filter(Report.category == category)
    rows = q.order_by(Report.created_at.desc()).limit(limit).all()

    if not latest_only:
        return [_to_out(r) for r in rows]

    seen: set[str] = set()
    latest: list[Report] = []
    for r in rows:
        if r.category in seen:
            continue
        seen.add(r.category)
        latest.append(r)
    return [_to_out(r) for r in latest]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int, db: Session = Depends(get_db)):
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(404, "Report not found")
    return _to_out(r)


@router.get("/articles/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, db: Session = Depends(get_db)):
    a = db.query(Article).filter(Article.id == article_id).first()
    if not a:
        raise HTTPException(404, "Article not found")
    return ArticleOut.model_validate(a)


@router.get("/{report_id}/audio")
def get_report_audio(
    report_id: int,
    engine: str | None = Query(None, description="'elevenlabs' | 'openai' — overrides user setting"),
    db: Session = Depends(get_db),
):
    """Stream the mp3 for this report's radio_script.

    Engine resolution order:
      1. explicit ?engine= query param (debug / admin override)
      2. user's Settings.channels.tts_engine
      3. auto (ElevenLabs if configured, else OpenAI fallback)
    """
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(404, "Report not found")
    if not (r.radio_script or "").strip():
        raise HTTPException(404, "Report has no radio_script")

    # If the caller didn't force an engine, check the owning user's preference.
    chosen_engine = engine
    if not chosen_engine:
        setting = db.query(Setting).filter(Setting.user_id == r.user_id).first()
        if setting and setting.channels:
            try:
                channels = json.loads(setting.channels)
                pref = channels.get("tts_engine")
                if isinstance(pref, str) and pref in ("elevenlabs", "openai"):
                    chosen_engine = pref
            except json.JSONDecodeError:
                pass

    try:
        path: Path = synthesize_to_file(r, engine=chosen_engine)
    except TTSUnavailable as exc:
        raise HTTPException(503, f"TTS unavailable: {exc}")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=f"report-{report_id}.mp3",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/generate", response_model=ReportGenerateResponse)
def generate_now(user_id: int = Query(...), db: Session = Depends(get_db)):
    try:
        created = generate_reports_for_user(db, user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    return ReportGenerateResponse(
        user_id=user_id,
        generated=len(created),
        reports=[_to_out(r) for r in created],
    )


# SSE progress stream: live events while the pipeline runs in a background thread.
# Runs generate_reports_for_user with an on_progress callback that pushes events
# into a thread-safe queue; the HTTP generator drains the queue as SSE frames.
_SENTINEL = object()


def _run_pipeline_in_thread(user_id: int, q: "queue.Queue[Any]") -> None:
    db = SessionLocal()
    try:
        def on_progress(event: dict[str, Any]) -> None:
            q.put(event)

        try:
            generate_reports_for_user(db, user_id, on_progress=on_progress)
        except Exception as exc:  # propagate to client as an error event
            logger.exception("pipeline thread failed for user_id=%s", user_id)
            q.put({"type": "error", "message": str(exc)})
    finally:
        db.close()
        q.put(_SENTINEL)


def _sse_format(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/generate/stream")
def generate_stream(user_id: int = Query(...)):
    q: "queue.Queue[Any]" = queue.Queue()
    thread = threading.Thread(
        target=_run_pipeline_in_thread,
        args=(user_id, q),
        daemon=True,
    )
    thread.start()

    def event_generator():
        # Initial comment keeps the connection open immediately (some proxies buffer).
        yield ": stream-open\n\n"
        while True:
            try:
                item = q.get(timeout=1.0)
            except queue.Empty:
                # Heartbeat comment; also lets the server notice client disconnects.
                yield ": keepalive\n\n"
                continue
            if item is _SENTINEL:
                break
            yield _sse_format(item)
            if isinstance(item, dict) and item.get("type") in ("done", "error"):
                # Drain sentinel before closing so the thread can exit cleanly.
                try:
                    while q.get_nowait() is not _SENTINEL:
                        pass
                except queue.Empty:
                    pass
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
