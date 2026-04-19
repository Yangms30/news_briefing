"""News collectors. Multi-source by default:
- Google News RSS (aggregator across many Korean outlets)
- 연합뉴스 (Yonhap) RSS — 국내 최대 공영 통신사, 카테고리별 feed
- 서울신문 RSS — 과제 주최사, 카테고리별 feed

Each client exposes `fetch(category) -> list[RawArticle]` returning articles
collected within the last `hours` window, capped at `per_category`. The
pipeline fans out to all available clients and dedupes by URL before
handing off to the TF-IDF clustering stage, which handles content-level
duplicates across sources.
"""
from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Iterable
from urllib.parse import quote_plus

import feedparser
import httpx

logger = logging.getLogger(__name__)


# ---------- Shared model ----------


@dataclass
class RawArticle:
    title: str
    link: str
    published: datetime | None
    source: str | None
    summary: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d


# ---------- Shared helpers ----------


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_published(entry) -> datetime | None:
    if getattr(entry, "published_parsed", None):
        return datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
    return None


def _extract_source_title(entry) -> str | None:
    src = getattr(entry, "source", None)
    if src and isinstance(src, dict):
        return src.get("title")
    if hasattr(entry, "source") and hasattr(entry.source, "title"):
        return entry.source.title
    return None


def _fetch_rss_url(
    url: str,
    *,
    source_name: str,
    timeout: float,
    max_attempts: int,
    backoff_base: float,
) -> feedparser.FeedParserDict | None:
    """HTTP GET + feedparser.parse with linear backoff. None on total failure.

    Individual RSS endpoints (especially Google News) are flaky; one bad
    attempt shouldn't blow up a category. Still degrades to None so the
    caller can treat it as "no articles from this source".
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(
                    url, headers={"User-Agent": "Mozilla/5.0 BriefBot/0.1"}
                )
                resp.raise_for_status()
                return feedparser.parse(resp.content)
        except Exception as exc:
            last_err = exc
            logger.warning(
                "[%s] RSS fetch failed (attempt %d/%d) %s: %s",
                source_name,
                attempt,
                max_attempts,
                url,
                exc,
            )
            if attempt < max_attempts:
                time.sleep(backoff_base * attempt)
    logger.warning(
        "[%s] RSS giving up after %d attempts: %s — %s",
        source_name,
        max_attempts,
        url,
        last_err,
    )
    return None


def _feed_to_articles(
    feed: feedparser.FeedParserDict,
    *,
    hours: int,
    per_category: int,
    default_source: str | None = None,
) -> list[RawArticle]:
    """Convert feedparser entries to RawArticle, apply time-window filter."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    out: list[RawArticle] = []
    # *2 so we can still hit per_category after time-window filtering.
    for entry in feed.entries[: per_category * 2]:
        published = _parse_published(entry)
        if published and published < cutoff:
            continue
        source_title = _extract_source_title(entry) or default_source
        out.append(
            RawArticle(
                title=_strip_html(getattr(entry, "title", "")),
                link=getattr(entry, "link", ""),
                published=published,
                source=source_title,
                summary=_strip_html(getattr(entry, "summary", "")),
            )
        )
        if len(out) >= per_category:
            break
    return out


# ---------- Google News (aggregator) ----------


# Category → Google News query (Korean, focused topics)
CATEGORY_QUERIES: dict[str, str] = {
    "정치": "정치 OR 국회 OR 대통령",
    "경제": "한국 경제 OR 금리 OR 환율",
    "사회": "사회 OR 사건 OR 사고",
    "국제": "국제 OR 외신 OR 해외",
    "스포츠": "스포츠 OR 야구 OR 축구 OR 손흥민",
    "IT/과학": "IT OR 인공지능 OR 반도체 OR 과학",
}

GOOGLE_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
)


class GoogleRSSClient:
    """Google News RSS aggregator (covers many Korean outlets internally)."""

    name = "google"

    def __init__(
        self,
        hours: int = 24,
        per_category: int = 20,
        timeout: float = 20.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
    ):
        self.hours = hours
        self.per_category = per_category
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def fetch(self, category: str) -> list[RawArticle]:
        query = CATEGORY_QUERIES.get(category, category)
        url = GOOGLE_RSS_TEMPLATE.format(query=quote_plus(query))
        feed = _fetch_rss_url(
            url,
            source_name=self.name,
            timeout=self.timeout,
            max_attempts=self.max_attempts,
            backoff_base=self.backoff_base,
        )
        if feed is None:
            return []
        articles = _feed_to_articles(
            feed, hours=self.hours, per_category=self.per_category
        )
        logger.info("[%s] collected %d articles for category=%s", self.name, len(articles), category)
        return articles

    def fetch_all(self, categories: list[str]) -> dict[str, list[RawArticle]]:
        return {c: self.fetch(c) for c in categories}


# ---------- 연합뉴스 ----------


class YonhapRSSClient:
    """연합뉴스 category RSS. IT/과학 falls back to the 산업 feed since there
    is no dedicated IT feed. Standalone site feeds tend to be more reliable
    than aggregators because there's no query layer."""

    name = "yonhap"
    DEFAULT_SOURCE = "연합뉴스"
    # BriefBot category → Yonhap slug
    CATEGORY_MAP: dict[str, str] = {
        "정치": "politics",
        "경제": "economy",
        "사회": "society",
        "국제": "international",
        "스포츠": "sports",
        "IT/과학": "industry",  # 연합 has no IT feed; 산업이 가장 근접
    }
    URL_TEMPLATE = "https://www.yna.co.kr/rss/{slug}.xml"

    def __init__(
        self,
        hours: int = 24,
        per_category: int = 20,
        timeout: float = 20.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
    ):
        self.hours = hours
        self.per_category = per_category
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def fetch(self, category: str) -> list[RawArticle]:
        slug = self.CATEGORY_MAP.get(category)
        if not slug:
            return []
        url = self.URL_TEMPLATE.format(slug=slug)
        feed = _fetch_rss_url(
            url,
            source_name=self.name,
            timeout=self.timeout,
            max_attempts=self.max_attempts,
            backoff_base=self.backoff_base,
        )
        if feed is None:
            return []
        articles = _feed_to_articles(
            feed,
            hours=self.hours,
            per_category=self.per_category,
            default_source=self.DEFAULT_SOURCE,
        )
        logger.info("[%s] collected %d articles for category=%s", self.name, len(articles), category)
        return articles


# ---------- 서울신문 ----------


class SeoulNewsRSSClient:
    """서울신문 category RSS. Thematically relevant because BriefBot is a
    submission for this very outlet's evaluation. No dedicated IT/과학 feed,
    so that category is simply skipped — Google News + Yonhap cover it."""

    name = "seoul"
    DEFAULT_SOURCE = "서울신문"
    CATEGORY_MAP: dict[str, str] = {
        "정치": "politics",
        "경제": "economy",
        "사회": "society",
        "국제": "international",
        "스포츠": "sports",
        # IT/과학: 전용 피드 없음. 생활(life)에 일부 섞여 있으나 signal 낮아 skip.
    }
    URL_TEMPLATE = "https://www.seoul.co.kr/xml/rss/rss_{slug}.xml"

    def __init__(
        self,
        hours: int = 24,
        per_category: int = 20,
        timeout: float = 20.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
    ):
        self.hours = hours
        self.per_category = per_category
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def fetch(self, category: str) -> list[RawArticle]:
        slug = self.CATEGORY_MAP.get(category)
        if not slug:
            return []
        url = self.URL_TEMPLATE.format(slug=slug)
        feed = _fetch_rss_url(
            url,
            source_name=self.name,
            timeout=self.timeout,
            max_attempts=self.max_attempts,
            backoff_base=self.backoff_base,
        )
        if feed is None:
            return []
        articles = _feed_to_articles(
            feed,
            hours=self.hours,
            per_category=self.per_category,
            default_source=self.DEFAULT_SOURCE,
        )
        logger.info("[%s] collected %d articles for category=%s", self.name, len(articles), category)
        return articles


# ---------- Multi-source aggregator ----------


class MultiSourceCollector:
    """Fan out to all configured clients, merge, dedupe by URL.

    Content-level duplicate detection (same story, different wording) is left
    to the TF-IDF clustering step downstream — cheap URL-set dedup here just
    prevents obvious double-counting when 연합뉴스 + Google News both surface
    the exact same URL.
    """

    def __init__(self, clients: Iterable[object] | None = None, hours: int = 24, per_category: int = 20):
        # `clients` anything with a .fetch(category) -> list[RawArticle]
        self.clients = list(clients) if clients is not None else [
            GoogleRSSClient(hours=hours, per_category=per_category),
            YonhapRSSClient(hours=hours, per_category=per_category),
            SeoulNewsRSSClient(hours=hours, per_category=per_category),
        ]
        self.hours = hours
        self.per_category = per_category

    def fetch(self, category: str) -> list[RawArticle]:
        merged: list[RawArticle] = []
        counts: dict[str, int] = {}
        for client in self.clients:
            try:
                articles = client.fetch(category)
            except Exception as exc:
                logger.exception(
                    "collector %s failed on category=%s: %s",
                    getattr(client, "name", type(client).__name__),
                    category,
                    exc,
                )
                articles = []
            counts[getattr(client, "name", type(client).__name__)] = len(articles)
            merged.extend(articles)

        # URL-level dedupe; clustering handles the rest.
        seen: set[str] = set()
        deduped: list[RawArticle] = []
        for a in merged:
            if not a.link or a.link in seen:
                continue
            seen.add(a.link)
            deduped.append(a)

        logger.info(
            "multi-source collected category=%s total=%d deduped=%d breakdown=%s",
            category,
            len(merged),
            len(deduped),
            counts,
        )
        return deduped

    def fetch_all(self, categories: list[str]) -> dict[str, list[RawArticle]]:
        return {c: self.fetch(c) for c in categories}
