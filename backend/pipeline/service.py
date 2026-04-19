"""High-level orchestration: collect → cluster → pick top-3 → summarize each → synthesize radio → persist."""
from __future__ import annotations
import json
import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from config import get_settings
from models import Article, Report, Setting
from schemas import ReportOut

from .analyzer import OpenAIAnalyzer
from .collector import MultiSourceCollector
from .preprocessor import cluster_articles, pick_top_articles

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


def _emit(cb: ProgressCallback | None, event: dict[str, Any]) -> None:
    if cb is None:
        return
    try:
        cb(event)
    except Exception:
        logger.exception("progress callback raised; continuing")


def generate_reports_for_user(
    db: Session,
    user_id: int,
    on_progress: ProgressCallback | None = None,
) -> list[Report]:
    cfg = get_settings()
    setting: Setting | None = db.query(Setting).filter(Setting.user_id == user_id).first()
    if not setting:
        raise ValueError(f"No settings found for user_id={user_id}")
    categories: list[str] = json.loads(setting.categories)
    if not categories:
        return []

    # Multi-source: Google News (aggregator) + 연합뉴스 + 서울신문. Each source is
    # optional — if one times out/404s, MultiSourceCollector still returns whatever
    # the others produced. URL-dedup happens inside the collector; content-dedup
    # by TF-IDF clustering downstream.
    collector = MultiSourceCollector(hours=cfg.ARTICLE_HOURS, per_category=cfg.COLLECT_PER_CATEGORY)
    analyzer = OpenAIAnalyzer()

    _emit(on_progress, {"type": "start", "categories": categories})

    created: list[Report] = []
    total = len(categories)
    for idx, category in enumerate(categories, 1):
        _emit(on_progress, {"type": "category_start", "category": category, "index": idx, "total": total})

        raw = collector.fetch(category)
        _emit(on_progress, {"type": "collected", "category": category, "count": len(raw)})
        if not raw:
            logger.info("No articles for %s, skipping", category)
            _emit(on_progress, {"type": "category_done", "category": category, "articles": 0})
            continue

        clusters = cluster_articles(raw, threshold=cfg.CLUSTER_THRESHOLD)
        _emit(on_progress, {"type": "clustered", "category": category, "count": len(clusters)})
        if not clusters:
            _emit(on_progress, {"type": "category_done", "category": category, "articles": 0})
            continue

        top_articles = pick_top_articles(clusters, n=3)
        if not top_articles:
            _emit(on_progress, {"type": "category_done", "category": category, "articles": 0})
            continue

        summaries: list[str] = []
        for a_idx, article in enumerate(top_articles, 1):
            _emit(
                on_progress,
                {
                    "type": "summarizing_article",
                    "category": category,
                    "article_index": a_idx,
                    "article_total": len(top_articles),
                    "article_title": article.title[:80],
                },
            )
            try:
                s = analyzer.summarize_article(category, article)
            except Exception as exc:
                logger.exception("summarize failed for %s / %s: %s", category, article.title, exc)
                s = article.summary or article.title
            summaries.append(s)

        _emit(on_progress, {"type": "synthesizing_radio", "category": category})
        radio = None
        try:
            radio = analyzer.synthesize_radio(category, top_articles, summaries)
        except Exception as exc:
            logger.exception("radio synth failed for %s: %s", category, exc)

        report = Report(user_id=user_id, category=category, radio_script=radio)
        db.add(report)
        db.flush()  # need report.id for articles

        for article, s in zip(top_articles, summaries):
            db.add(
                Article(
                    user_id=user_id,
                    report_id=report.id,
                    category=category,
                    title=article.title[:500],
                    summary=s,
                    link=article.link,
                    source=article.source,
                    published_at=article.published,
                )
            )
        # Commit this category immediately so that:
        #   1) downstream sessions (dashboard polling, dispatcher) see the row
        #   2) the SSE stream can ship the fully-realized report to the client,
        #      letting the UI render + enable playback one category at a time
        #      instead of waiting for the whole batch.
        db.commit()
        db.refresh(report)
        created.append(report)
        _emit(
            on_progress,
            {
                "type": "category_done",
                "category": category,
                "articles": len(top_articles),
                "report": ReportOut.model_validate(report).model_dump(mode="json"),
            },
        )

    logger.info("Generated %d reports for user_id=%d", len(created), user_id)
    _emit(on_progress, {"type": "done", "generated": len(created)})
    return created
