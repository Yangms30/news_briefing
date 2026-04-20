"""Slack sender with two modes:

- **Webhook** (legacy, text-only): simple `https://hooks.slack.com/...` POST
  with Block Kit. Cannot upload files.
- **Bot token** (xoxb-...): uses `chat.postMessage` + `files.upload_v2`
  3-step flow to post the report AND upload per-category mp3s as a threaded
  reply. The mp3s render as inline audio players inside Slack.

Which mode gets used is chosen by the dispatcher based on what's saved in
settings.channels — either `slack` (webhook URL) or the pair
`slack_bot_token` + `slack_channel_id`.
"""
from __future__ import annotations
import logging
from typing import Any

import httpx

from models import Report
from services.tts import TTSUnavailable, synthesize_to_file

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_BOT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

_FILENAME_SAFE: dict[str, str] = {
    "정치": "politics",
    "경제": "economy",
    "사회": "society",
    "국제": "international",
    "스포츠": "sports",
    "IT/과학": "it-science",
}


def _mp3_filename(report: Report) -> str:
    slug = _FILENAME_SAFE.get(report.category) or "category"
    return f"seosin-{slug}-{report.id}.mp3"


# ---------- Block Kit rendering (shared by both modes) ----------


def _build_blocks(user_name: str, reports: list[Report]) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[서신 · 書信] {user_name}님의 오늘의 리포트"[:150]},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"분야 {len(reports)}개 · 기사 {sum(len(r.articles) for r in reports)}건"}
            ],
        },
        {"type": "divider"},
    ]
    for r in reports:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*■ {r.category}*"}}
        )
        for a in r.articles:
            text = f"*<{a.link}|{a.title[:120]}>*\n_{a.source or '출처 미상'}_\n{a.summary[:600]}"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}})
        if r.radio_script:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"🎧 *{r.category} 라디오*\n{r.radio_script[:2900]}"}
                    ],
                }
            )
        blocks.append({"type": "divider"})
    return blocks


# ---------- Mode 1: Webhook (text only) ----------


def _send_webhook(webhook_url: str, user_name: str, reports: list[Report]) -> tuple[str, str | None]:
    payload = {
        "text": f"[서신 · 書信] {user_name}님의 오늘의 리포트",
        "blocks": _build_blocks(user_name, reports),
    }
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=_WEBHOOK_TIMEOUT)
    except httpx.HTTPError as exc:
        logger.warning("slack webhook error: %s", exc)
        return "failed", str(exc)
    if resp.status_code >= 400:
        logger.warning("slack webhook non-2xx: %s %s", resp.status_code, resp.text[:200])
        return "failed", f"http {resp.status_code}: {resp.text[:200]}"
    return "success", None


# ---------- Mode 2: Bot token (audio attachments) ----------


def _slack_api_post(
    method: str, token: str, *, json_body: dict[str, Any] | None = None, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call a Slack Web API method with Bearer auth. Returns parsed JSON.

    Slack always returns 200 with `{ok: bool, error?: str}` — raise nothing
    here; callers inspect `ok` and surface `error`.
    """
    url = f"https://slack.com/api/{method}"
    headers = {"Authorization": f"Bearer {token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        resp = httpx.post(url, headers=headers, json=json_body, timeout=_BOT_TIMEOUT)
    else:
        resp = httpx.post(url, headers=headers, data=data or {}, timeout=_BOT_TIMEOUT)
    try:
        return resp.json()
    except Exception:
        return {"ok": False, "error": f"non-json response ({resp.status_code})", "_raw": resp.text[:200]}


def _upload_audio_to_slack(
    token: str,
    channel_id: str,
    thread_ts: str | None,
    report: Report,
    mp3_bytes: bytes,
) -> tuple[bool, str | None]:
    """files.upload_v2 3-step flow for a single report's mp3.

    Returns (ok, error_message).
    """
    fname = _mp3_filename(report)
    # Step 1: request an upload URL
    step1 = _slack_api_post(
        "files.getUploadURLExternal",
        token,
        data={"filename": fname, "length": str(len(mp3_bytes))},
    )
    if not step1.get("ok"):
        return False, f"getUploadURL: {step1.get('error')}"
    upload_url = step1.get("upload_url")
    file_id = step1.get("file_id")
    if not upload_url or not file_id:
        return False, "getUploadURL missing upload_url/file_id"

    # Step 2: POST bytes to returned URL.
    try:
        r2 = httpx.post(upload_url, content=mp3_bytes, timeout=_BOT_TIMEOUT)
    except httpx.HTTPError as exc:
        return False, f"upload bytes: {exc}"
    if r2.status_code >= 400:
        return False, f"upload bytes http {r2.status_code}"

    # Step 3: complete + share (thread_ts → appears as thread reply).
    body: dict[str, Any] = {
        "files": [{"id": file_id, "title": f"{report.category} 라디오"}],
        "channel_id": channel_id,
    }
    if thread_ts:
        body["thread_ts"] = thread_ts
    step3 = _slack_api_post("files.completeUploadExternal", token, json_body=body)
    if not step3.get("ok"):
        return False, f"completeUpload: {step3.get('error')}"
    return True, None


def _send_bot(
    token: str,
    channel_id: str,
    user_name: str,
    reports: list[Report],
    tts_engine: str | None = None,
) -> tuple[str, str | None]:
    # Step A: post the report as the parent message (text + blocks).
    post = _slack_api_post(
        "chat.postMessage",
        token,
        json_body={
            "channel": channel_id,
            "text": f"[서신 · 書信] {user_name}님의 오늘의 리포트",
            "blocks": _build_blocks(user_name, reports),
        },
    )
    if not post.get("ok"):
        err = post.get("error", "unknown")
        logger.warning("slack chat.postMessage failed: %s", err)
        return "failed", f"chat.postMessage: {err}"
    thread_ts = post.get("ts")

    # Step B: synthesize + upload each report's mp3 as a threaded reply.
    # One file per category so users can skim by section; Slack renders
    # each file with an inline audio player.
    uploaded = 0
    failures: list[str] = []
    for r in reports:
        if not (r.radio_script or "").strip():
            continue
        try:
            path = synthesize_to_file(r, engine=tts_engine)
        except TTSUnavailable as exc:
            logger.warning("slack: TTS unavailable for report_id=%s: %s", r.id, exc)
            failures.append(f"{r.category}: TTS unavailable")
            continue
        except Exception as exc:
            logger.exception("slack: TTS error for report_id=%s: %s", r.id, exc)
            failures.append(f"{r.category}: TTS error")
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            failures.append(f"{r.category}: read mp3 {exc}")
            continue
        ok, err = _upload_audio_to_slack(token, channel_id, thread_ts, r, data)
        if ok:
            uploaded += 1
        else:
            failures.append(f"{r.category}: {err}")

    logger.info(
        "slack bot: uploaded %d/%d mp3(s), %d failures (engine=%s)",
        uploaded,
        sum(1 for r in reports if (r.radio_script or "").strip()),
        len(failures),
        tts_engine or "auto",
    )
    # Parent text message landed — treat the whole dispatch as a success.
    # Per-file upload failures are logged but don't flip the channel's
    # status so one flaky mp3 doesn't mask a delivered report.
    if failures and uploaded == 0:
        return "failed", "; ".join(failures[:3])
    return "success", None


# ---------- Public entry point ----------


class SlackSender:
    """Facade that picks webhook vs bot-token mode from the config dict."""

    @staticmethod
    def send(
        config: Any,
        user_name: str,
        reports: list[Report],
        tts_engine: str | None = None,
    ) -> tuple[str, str | None]:
        if not reports:
            return "skipped", "no reports to send"

        # Backward compat: older callers pass a plain webhook URL string.
        if isinstance(config, str):
            if not config.startswith("http"):
                return "failed", "invalid webhook url"
            return _send_webhook(config, user_name, reports)

        if isinstance(config, dict):
            mode = config.get("mode")
            if mode == "bot":
                token = config.get("token")
                channel_id = config.get("channel_id")
                if not isinstance(token, str) or not token.startswith("xoxb-"):
                    return "failed", "invalid bot token"
                if not isinstance(channel_id, str) or not channel_id.strip():
                    return "failed", "invalid channel_id"
                return _send_bot(token, channel_id.strip(), user_name, reports, tts_engine)
            if mode == "webhook":
                url = config.get("url")
                if not isinstance(url, str) or not url.startswith("http"):
                    return "failed", "invalid webhook url"
                return _send_webhook(url, user_name, reports)

        return "failed", "unknown slack config"
