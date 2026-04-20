"""News collectors. Multi-source by default:
- Google News RSS (aggregator across many Korean outlets)
- 연합뉴스 (Yonhap) RSS — 국내 최대 공영 통신사, 카테고리별 feed
- 서울신문 RSS — 과제 주최사, 카테고리별 feed
- 네이버 검색 API — 포털 큐레이션 반영 (keys: NAVER_CLIENT_ID/SECRET)

Each client exposes `fetch(category) -> list[RawArticle]` returning articles
collected within the last `hours` window, capped at `per_category`. The
pipeline fans out to all available clients and dedupes by URL/title before
handing off to the TF-IDF clustering stage, which handles content-level
duplicates across sources.
"""
from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from time import mktime
from typing import Iterable
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx

from config import get_settings

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
                    url, headers={"User-Agent": "Mozilla/5.0 Seosin/0.1"}
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


# ---------- 네이버 검색 API ----------


# Domain → Korean outlet name. Naver's Search API doesn't send a structured
# `source` field, so we infer the publisher from the originallink host. Only
# major outlets are here; unknowns fall back to the bare domain.
_NAVER_DOMAIN_TO_SOURCE: dict[str, str] = {
    "yna.co.kr": "연합뉴스",
    "yonhapnews.co.kr": "연합뉴스",
    "yonhapnewstv.co.kr": "연합뉴스TV",
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "seoul.co.kr": "서울신문",
    "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제",
    "newsis.com": "뉴시스",
    "news1.kr": "뉴스1",
    "ytn.co.kr": "YTN",
    "kbs.co.kr": "KBS",
    "sbs.co.kr": "SBS",
    "imbc.com": "MBC",
    "mbc.co.kr": "MBC",
    "etnews.com": "전자신문",
    "zdnet.co.kr": "ZDNet Korea",
    "bloter.net": "블로터",
    "inews24.com": "아이뉴스24",
    "hankookilbo.com": "한국일보",
    "segye.com": "세계일보",
    "munhwa.com": "문화일보",
    "kukinews.com": "쿠키뉴스",
    "newspim.com": "뉴스핌",
    "edaily.co.kr": "이데일리",
    "sedaily.com": "서울경제",
    "mt.co.kr": "머니투데이",
    "sisajournal.com": "시사저널",
    "ohmynews.com": "오마이뉴스",
    "pressian.com": "프레시안",
}


def _source_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return None
    host = host.lower().lstrip("www.")
    for suffix, name in _NAVER_DOMAIN_TO_SOURCE.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    # Fallback: first meaningful segment of the domain (e.g. "some-local-news")
    parts = host.split(".")
    return parts[0] if parts else None


def _clean_naver_markup(text: str) -> str:
    """Naver wraps matched keywords in <b>…</b> and HTML-encodes quotes/etc.
    Strip both so the text enters TF-IDF and the user-visible title cleanly.
    """
    if not text:
        return ""
    # Remove keyword-highlight <b> tags specifically (leave other legit HTML
    # alone for _strip_html to handle).
    text = re.sub(r"</?b>", "", text, flags=re.IGNORECASE)
    text = unescape(text)  # &quot; → ", &amp; → &, etc.
    return _strip_html(text)


def _parse_naver_pub_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class NaverSearchClient:
    """네이버 뉴스 검색 API. 무료 25,000건/일.

    Uses the same Korean-keyword queries as GoogleRSSClient so the results
    are comparable, but sorts by "date" (newest first) and relies on the
    `originallink` field to recover the publisher. Credentials come from
    the env — if either is missing the client returns an empty list and
    the other sources continue as usual (graceful degrade).
    """

    name = "naver"
    ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
    # Naver 검색은 Google News 식 "A OR B" 연산자를 지원하지 않는다 (공백 =
    # 암묵적 AND). 카테고리 의미가 충분히 분명한 단일 한국어 키워드를 써야
    # 매칭이 제대로 잡힌다. 포털 큐레이션 자체가 분류를 돕기 때문에 단일
    # 키워드만으로도 해당 카테고리 기사가 풍부하게 나옴.
    CATEGORY_QUERIES: dict[str, str] = {
        "정치": "정치",
        "경제": "경제",
        "사회": "사회",
        "국제": "국제",
        "스포츠": "스포츠",
        "IT/과학": "IT 과학",
    }

    def __init__(
        self,
        hours: int = 24,
        per_category: int = 20,
        timeout: float = 15.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
    ):
        cfg = get_settings()
        self.client_id = cfg.NAVER_CLIENT_ID
        self.client_secret = cfg.NAVER_CLIENT_SECRET
        self.hours = hours
        self.per_category = per_category
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def fetch(self, category: str) -> list[RawArticle]:
        if not self.client_id or not self.client_secret:
            # No-op: keys not configured. Other clients still run.
            return []

        query = self.CATEGORY_QUERIES.get(category, category)
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {
            "query": query,
            # Naver's API max is 100 per call; pull extra so we can filter
            # by the 24h window and still keep per_category items.
            "display": max(self.per_category * 2, 30),
            "start": 1,
            "sort": "date",   # newest first
        }

        last_err: Exception | None = None
        data = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = httpx.get(self.ENDPOINT, params=params, headers=headers, timeout=self.timeout)
                if resp.status_code == 401 or resp.status_code == 403:
                    logger.warning("[%s] auth failed (%s) — check NAVER_CLIENT_ID/SECRET", self.name, resp.status_code)
                    return []
                if resp.status_code == 429:
                    logger.warning("[%s] rate limited (attempt %d)", self.name, attempt)
                    last_err = RuntimeError(f"http 429 {resp.text[:100]}")
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    break
            except Exception as exc:
                last_err = exc
                logger.warning("[%s] fetch failed attempt %d/%d for %s: %s", self.name, attempt, self.max_attempts, category, exc)
            if attempt < self.max_attempts:
                time.sleep(self.backoff_base * attempt)

        if data is None:
            logger.warning("[%s] giving up on %s after %d attempts: %s", self.name, category, self.max_attempts, last_err)
            return []

        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=self.hours)
        out: list[RawArticle] = []
        for item in data.get("items") or []:
            title = _clean_naver_markup(item.get("title", ""))
            if not title:
                continue
            link = item.get("originallink") or item.get("link") or ""
            description = _clean_naver_markup(item.get("description", ""))
            pub = _parse_naver_pub_date(item.get("pubDate"))
            if pub and pub < cutoff:
                continue
            out.append(
                RawArticle(
                    title=title,
                    link=link,
                    published=pub,
                    source=_source_from_url(link),
                    summary=description,
                )
            )
            if len(out) >= self.per_category:
                break
        logger.info("[%s] collected %d articles for category=%s", self.name, len(out), category)
        return out


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
        # NaverSearchClient is included by default — if NAVER_CLIENT_ID/SECRET
        # aren't set it silently returns [] so the other three sources still work.
        self.clients = list(clients) if clients is not None else [
            GoogleRSSClient(hours=hours, per_category=per_category),
            YonhapRSSClient(hours=hours, per_category=per_category),
            SeoulNewsRSSClient(hours=hours, per_category=per_category),
            NaverSearchClient(hours=hours, per_category=per_category),
        ]
        self.hours = hours
        self.per_category = per_category

    def fetch(self, category: str) -> list[RawArticle]:
        # Imported lazily to avoid a circular dep between collector and
        # preprocessor (preprocessor imports RawArticle from this module).
        from .preprocessor import normalize_title

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

        # Two-stage dedupe before TF-IDF clustering:
        #   1) exact URL match — catches an article syndicated under the same
        #      link twice (rare, but defensive).
        #   2) normalized title match — catches the *same* story republished
        #      under different URLs (e.g. Naver syndicating a Yonhap article,
        #      or Google News pointing at a different outlet's copy). TF-IDF
        #      handles near-duplicates, but exact-title copies pollute cluster
        #      sizes and should be collapsed here.
        seen_urls: set[str] = set()
        seen_title_keys: set[str] = set()
        deduped: list[RawArticle] = []
        for a in merged:
            if not a.link or a.link in seen_urls:
                continue
            title_key = normalize_title(a.title).strip().lower()
            if title_key and title_key in seen_title_keys:
                continue
            seen_urls.add(a.link)
            if title_key:
                seen_title_keys.add(title_key)
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
