"""LLM analyzer: per-article 3-line summary + per-category radio synthesis.

Default provider: OpenAI (gpt-5-mini). GeminiAnalyzer kept as legacy fallback.

GPT-5 family note: does not accept custom `temperature` (always default 1.0).
"""
from __future__ import annotations
import logging
import re
import time

import google.generativeai as genai
from openai import OpenAI

from config import get_settings
from prompts.article_summary import ARTICLE_SUMMARY_SYSTEM, ARTICLE_SUMMARY_USER_TEMPLATE
from prompts.radio_script import RADIO_SYSTEM, RADIO_USER_TEMPLATE

from .collector import RawArticle

logger = logging.getLogger(__name__)


def _fallback_summary(article: RawArticle) -> str:
    """If LLM fails/empty, degrade to RSS summary or title."""
    text = (article.summary or "").strip() or article.title
    text = re.sub(r"\s+", " ", text).strip()
    # Try to split into ~3 sentences by punctuation
    parts = re.split(r"(?<=[.!?。])\s+|(?<=[다요][.!?。])\s+", text)
    parts = [p for p in parts if p]
    if len(parts) >= 3:
        return "\n".join(parts[:3])
    if len(parts) == 2:
        return "\n".join(parts + [article.title])
    return "\n".join([text, article.title, article.source or ""]).strip()


def _build_articles_block(articles: list[RawArticle], summaries: list[str]) -> str:
    parts = []
    for i, (a, s) in enumerate(zip(articles, summaries), 1):
        src = a.source or "출처 미상"
        parts.append(f"[기사{i} | {src}]\n제목: {a.title}\n요약:\n{s}")
    return "\n\n".join(parts)


# ============================================================
# OpenAI (default — gpt-5-mini)
# ============================================================

class OpenAIAnalyzer:
    def __init__(self):
        cfg = get_settings()
        if not cfg.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set in .env")
        self.client = OpenAI(api_key=cfg.OPENAI_API_KEY)
        self.model_name = cfg.OPENAI_MODEL
        self.max_retries = cfg.LLM_MAX_RETRIES

    def summarize_article(self, category: str, article: RawArticle) -> str:
        user = ARTICLE_SUMMARY_USER_TEMPLATE.format(
            category=category,
            title=article.title,
            source=article.source or "출처 미상",
            body=(article.summary or article.title).strip(),
        )
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": ARTICLE_SUMMARY_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                )
                text = (resp.choices[0].message.content or "").strip()
                if text and len(text) >= 30:
                    return text
                logger.warning("article summary too short (attempt %d)", attempt)
            except Exception as exc:
                logger.warning("article summary error (attempt %d): %s", attempt, exc)
                time.sleep(0.5 * (attempt + 1))
        return _fallback_summary(article)

    def synthesize_radio(self, category: str, articles: list[RawArticle], summaries: list[str]) -> str | None:
        block = _build_articles_block(articles, summaries)
        user = RADIO_USER_TEMPLATE.format(
            category=category,
            n=len(articles),
            articles_block=block,
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": RADIO_SYSTEM},
                    {"role": "user", "content": user},
                ],
            )
            text = (resp.choices[0].message.content or "").strip()
            return text or None
        except Exception as exc:
            logger.warning("radio synth error: %s", exc)
            return None


# ============================================================
# Gemini (legacy fallback)
# ============================================================

class GeminiAnalyzer:
    def __init__(self):
        cfg = get_settings()
        if not cfg.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set in .env")
        genai.configure(api_key=cfg.GEMINI_API_KEY)
        self.model_name = cfg.GEMINI_MODEL
        self.max_retries = cfg.LLM_MAX_RETRIES
        self._model = genai.GenerativeModel(
            self.model_name,
            generation_config={"temperature": 0.5},
        )

    def summarize_article(self, category: str, article: RawArticle) -> str:
        user = ARTICLE_SUMMARY_USER_TEMPLATE.format(
            category=category,
            title=article.title,
            source=article.source or "출처 미상",
            body=(article.summary or article.title).strip(),
        )
        prompt = f"{ARTICLE_SUMMARY_SYSTEM}\n\n{user}"
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._model.generate_content(prompt)
                text = (resp.text or "").strip()
                if text and len(text) >= 30:
                    return text
                logger.warning("article summary too short (attempt %d)", attempt)
            except Exception as exc:
                logger.warning("article summary error (attempt %d): %s", attempt, exc)
                time.sleep(0.5 * (attempt + 1))
        return _fallback_summary(article)

    def synthesize_radio(self, category: str, articles: list[RawArticle], summaries: list[str]) -> str | None:
        block = _build_articles_block(articles, summaries)
        user = RADIO_USER_TEMPLATE.format(
            category=category,
            n=len(articles),
            articles_block=block,
        )
        prompt = f"{RADIO_SYSTEM}\n\n{user}"
        try:
            resp = self._model.generate_content(prompt)
            text = (resp.text or "").strip()
            return text or None
        except Exception as exc:
            logger.warning("radio synth error: %s", exc)
            return None
