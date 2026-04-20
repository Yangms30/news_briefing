"""Email sender: one comprehensive email with all category reports.

The email body carries the text content (HTML + plain-text alternative),
and each report's radio script is synthesized to mp3 (OpenAI gpt-4o-mini-tts)
and attached so the recipient can listen on-the-go without opening the web
app. Synthesis failures degrade gracefully: that category's mp3 is skipped
but the text email still goes out.
"""
from __future__ import annotations
import logging
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from config import get_settings
from models import Report
from services.tts import TTSUnavailable, synthesize_to_file

logger = logging.getLogger(__name__)


# Filesystem-safe mapping for Korean category names used as mp3 filenames.
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


def _render_report_section(report: Report) -> str:
    articles_html = "".join(
        f"""
        <div style="padding:14px 16px;background:#fff7f0;border-radius:10px;margin:10px 0;border:1px solid #fde4d1">
          <div style="font-size:15px;font-weight:600;color:#1f2937;margin-bottom:6px;line-height:1.4">{escape(a.title[:200])}</div>
          <div style="font-size:12px;color:#9ca3af;margin-bottom:8px">{escape(a.source or '출처 미상')}</div>
          <div style="font-size:13px;color:#4b5563;line-height:1.6;white-space:pre-line">{escape(a.summary)}</div>
          <div style="margin-top:10px"><a href="{escape(a.link)}" style="display:inline-block;padding:6px 12px;background:#f26930;color:#fff;border-radius:6px;font-size:12px;text-decoration:none">원문 보기 →</a></div>
        </div>
        """
        for a in report.articles
    )
    radio = report.radio_script or "(라디오 스크립트 없음)"
    return f"""
    <section style="margin:28px 0 0">
      <div style="display:inline-block;padding:4px 10px;background:#f26930;color:#fff;border-radius:999px;font-size:12px;letter-spacing:0.04em;font-weight:600">{escape(report.category)}</div>
      <div style="margin-top:14px">{articles_html}</div>
      <details style="margin-top:12px;background:#fafafa;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px">
        <summary style="cursor:pointer;font-size:13px;font-weight:600;color:#111827">🎧 {escape(report.category)} 라디오 스크립트</summary>
        <div style="margin-top:8px;font-size:13px;color:#374151;line-height:1.7;white-space:pre-line">{escape(radio)}</div>
      </details>
    </section>
    """


def _render_html(user_name: str, reports: list[Report], audio_count: int) -> str:
    sections = "".join(_render_report_section(r) for r in reports)
    title = escape(user_name) + "님, 오늘의 서신 리포트입니다"
    audio_badge = (
        f"""
    <div style="display:inline-block;margin-top:10px;padding:6px 14px;background:#fff7f0;color:#9a3412;border:1px solid #fde4d1;border-radius:999px;font-size:12px;font-weight:600">
      🎧 분야별 라디오 mp3 {audio_count}건이 이 메일에 첨부되어 있습니다
    </div>"""
        if audio_count > 0
        else ""
    )
    return f"""<!doctype html>
<html lang="ko"><body style="margin:0;padding:24px;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Pretendard','Segoe UI',sans-serif">
  <div style="max-width:680px;margin:0 auto;background:#fff;border-radius:14px;padding:32px;border:1px solid #e5e7eb">
    <div style="display:inline-block;padding:8px 16px;background:#fff7f0;border:1px solid #fde4d1;border-radius:10px;margin-bottom:16px">
      <div style="font-size:15px;color:#f26930;font-weight:700;letter-spacing:0.04em;line-height:1.1">
        서신 <span style="color:rgba(242,105,48,0.7);font-weight:600;font-size:13px">書信</span>
      </div>
      <div style="font-size:11px;color:#9a3412;margin-top:2px">오늘의 AI 뉴스 편지</div>
    </div>
    <h1 style="margin:4px 0 4px;font-size:24px;line-height:1.35;color:#111827">{title}</h1>
    <div style="font-size:13px;color:#6b7280">분야 {len(reports)}개 · 기사 {sum(len(r.articles) for r in reports)}건</div>
    {audio_badge}
    <hr style="border:none;border-top:1px solid #f3f4f6;margin:20px 0 0">
    {sections}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0 16px">
    <div style="font-size:11px;color:#9ca3af">서신 · 書信 — 가벼운 LLM으로 똑똑하게</div>
  </div>
</body></html>"""


def _render_text(user_name: str, reports: list[Report]) -> str:
    lines = [f"{user_name}님, 오늘의 서신 리포트입니다", "=" * 40]
    for r in reports:
        lines.append("")
        lines.append(f"■ {r.category}")
        for i, a in enumerate(r.articles, 1):
            lines.append(f"  {i}. {a.title}")
            lines.append(f"     출처: {a.source or '출처 미상'}")
            lines.append(f"     {a.summary}")
            lines.append(f"     원문: {a.link}")
        if r.radio_script:
            lines.append("")
            lines.append(f"  [{r.category} 라디오]")
            lines.append(f"  {r.radio_script}")
    return "\n".join(lines)


def _synthesize_audio_for_reports(
    reports: list[Report],
    tts_engine: str | None = None,
) -> list[tuple[Report, bytes]]:
    """Return (report, mp3_bytes) pairs for each report that produced audio.

    Skips reports without a radio_script and any whose TTS call fails so the
    rest of the email still goes through. `tts_engine` forwards the user's
    Settings preference so email attachments match what the dashboard radio
    player would produce.
    """
    results: list[tuple[Report, bytes]] = []
    for r in reports:
        if not (r.radio_script or "").strip():
            continue
        try:
            path = synthesize_to_file(r, engine=tts_engine)
        except TTSUnavailable as exc:
            logger.warning("email: TTS unavailable for report_id=%s: %s", r.id, exc)
            continue
        except Exception as exc:
            logger.exception("email: TTS synthesis error for report_id=%s: %s", r.id, exc)
            continue
        try:
            with open(path, "rb") as f:
                results.append((r, f.read()))
        except OSError as exc:
            logger.warning("email: failed to read mp3 %s: %s", path, exc)
    return results


class EmailSender:
    @staticmethod
    def send(
        to_email: str,
        user_name: str,
        reports: list[Report],
        tts_engine: str | None = None,
    ) -> tuple[str, str | None]:
        cfg = get_settings()
        if not cfg.SMTP_USER or not cfg.SMTP_PASSWORD:
            return "failed", "SMTP credentials not configured"
        if not to_email or "@" not in to_email:
            return "failed", "invalid recipient"
        if not reports:
            return "skipped", "no reports to send"

        # Synthesize audio first so the HTML body can accurately state the
        # attachment count (or skip the badge if all synthesis failed).
        audio_pairs = _synthesize_audio_for_reports(reports, tts_engine)
        audio_count = len(audio_pairs)

        msg = EmailMessage()
        cats = ", ".join(r.category for r in reports)
        msg["Subject"] = f"[서신] 오늘의 리포트 ({cats})"
        msg["From"] = cfg.SMTP_FROM or cfg.SMTP_USER
        msg["To"] = to_email
        msg.set_content(_render_text(user_name, reports))
        msg.add_alternative(_render_html(user_name, reports, audio_count), subtype="html")

        for r, data in audio_pairs:
            msg.add_attachment(
                data,
                maintype="audio",
                subtype="mpeg",
                filename=_mp3_filename(r),
            )
        logger.info(
            "email: prepared %d mp3 attachments out of %d reports (engine=%s)",
            audio_count,
            len(reports),
            tts_engine or "auto",
        )

        ctx = ssl.create_default_context()
        try:
            with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=60) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("email send error: %s", exc)
            return "failed", str(exc)
        return "success", None
