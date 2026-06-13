"""Gmail SMTP로 카테고리별 요약 뉴스레터를 발송한다."""
from __future__ import annotations

import logging
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Sequence

from fetch import Article

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _subject(now: datetime) -> str:
    wd = _WEEKDAYS[now.weekday()]
    slot = "오전" if now.hour < 12 else "오후"
    return f"[뉴스다이제스트] {now:%Y.%m.%d} ({wd}) {slot}"


_BULLET_RE = re.compile(r'^[•*\-]\s+')
_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
_SOURCE_RE = re.compile(r'\s*\(?\s*출처\s*[:：]\s*([^)]+?)\)?\s*$')


def _strip_source(s: str) -> tuple[str, str]:
    """문자열 끝의 (출처: …)를 추출. (본문만, 출처문자열) 반환."""
    m = _SOURCE_RE.search(s)
    if m:
        return s[:m.start()].strip(), f"출처: {m.group(1).strip()}"
    return s, ""


def _parse_summary(text: str) -> list[dict]:
    """요약 텍스트를 [{'headline','body','source'}, ...] 리스트로 파싱."""
    items: list[dict] = []
    current: dict | None = None

    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if _BULLET_RE.match(ln):
            if current:
                items.append(current)
            headline = _BULLET_RE.sub("", ln)
            headline = _BOLD_RE.sub(r"\1", headline).strip()
            headline, src = _strip_source(headline)
            current = {"headline": headline, "body": [], "source": src}
        elif ln.startswith("(출처") or ln.startswith("출처:") or ln.startswith("출처 "):
            if current:
                _, src = _strip_source(ln if ln.startswith("(") else f"({ln})")
                current["source"] = src or ln.strip("()")
        else:
            line_text, src = _strip_source(ln)
            if current:
                if line_text:
                    current["body"].append(line_text)
                if src and not current["source"]:
                    current["source"] = src
    if current:
        items.append(current)
    return items


def _bullets_to_html(text: str) -> str:
    """구조화된 요약을 헤드라인+본문+출처 HTML로 변환."""
    items = _parse_summary(text)
    if not items:
        return f"<p>{_escape(text)}</p>"

    html_items = []
    for it in items:
        body = " ".join(it["body"]).strip()
        parts = []
        if it["headline"]:
            parts.append(
                f"<div style='font-weight:600;color:#1a1a1a;font-size:15px;"
                f"margin-bottom:5px;line-height:1.4;'>{_escape(it['headline'])}</div>"
            )
        if body:
            parts.append(
                f"<div style='color:#333;line-height:1.65;font-size:14px;'>"
                f"{_escape(body)}</div>"
            )
        if it["source"]:
            parts.append(
                f"<div style='margin-top:5px;color:#888;font-size:12px;'>"
                f"{_escape(it['source'])}</div>"
            )
        html_items.append(
            f"<li style='margin-bottom:18px;padding-left:4px;'>"
            + "".join(parts) + "</li>"
        )
    return (
        "<ul style='padding-left:20px;margin:10px 0;'>"
        + "".join(html_items) + "</ul>"
    )


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _top_links_html(articles: Sequence[Article], limit: int = 5) -> str:
    if not articles:
        return ""
    items = []
    for a in articles[:limit]:
        items.append(
            f"<li style='margin:2px 0;'>"
            f"<a href='{_escape(a.link)}' style='color:#1a73e8;text-decoration:none;'>"
            f"{_escape(a.title)}</a> "
            f"<span style='color:#888;font-size:12px;'>— {_escape(a.source)}</span>"
            f"</li>"
        )
    return (
        "<details style='margin-top:8px;'>"
        "<summary style='cursor:pointer;color:#555;font-size:13px;'>원문 보기</summary>"
        "<ul style='padding-left:20px;margin:4px 0;font-size:13px;'>"
        + "".join(items)
        + "</ul></details>"
    )


def build_html(summaries: dict[str, str], articles_by_cat: dict[str, list[Article]], now: datetime) -> str:
    wd = _WEEKDAYS[now.weekday()]
    slot = "오전" if now.hour < 12 else "오후"
    sections = []
    for cat, summary in summaries.items():
        display_cat = cat.replace("_", "/")
        articles = articles_by_cat.get(cat, [])
        sections.append(
            f"<section style='margin-bottom:28px;'>"
            f"<h2 style='border-bottom:2px solid #1a73e8;padding-bottom:6px;color:#1a1a1a;font-size:18px;'>"
            f"📌 {_escape(display_cat)} <span style='color:#888;font-size:13px;font-weight:normal;'>({len(articles)}건)</span>"
            f"</h2>"
            f"{_bullets_to_html(summary)}"
            f"{_top_links_html(articles)}"
            f"</section>"
        )

    return f"""<!doctype html>
<html><body style='font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
                   max-width:680px;margin:0 auto;padding:20px;color:#222;line-height:1.6;'>
  <header style='margin-bottom:24px;'>
    <h1 style='margin:0;font-size:22px;color:#1a73e8;'>📰 오늘의 뉴스 다이제스트</h1>
    <p style='margin:4px 0 0;color:#666;font-size:14px;'>{now:%Y년 %m월 %d일} ({wd}) {slot} · Gemini 요약</p>
  </header>
  {''.join(sections)}
  <footer style='margin-top:32px;padding-top:12px;border-top:1px solid #eee;color:#999;font-size:12px;'>
    GitHub Actions로 자동 발송됨 · 매일 07:00 / 17:00 KST
  </footer>
</body></html>"""


def send(
    sender: str,
    app_password: str,
    recipient: str,
    summaries: dict[str, str],
    articles_by_cat: dict[str, list[Article]],
) -> None:
    now = datetime.now(KST)
    msg = EmailMessage()
    msg["Subject"] = _subject(now)
    msg["From"] = sender
    msg["To"] = recipient

    html = build_html(summaries, articles_by_cat, now)
    # plain-text fallback
    plain_lines = [_subject(now), ""]
    for cat, summary in summaries.items():
        plain_lines.append(f"[{cat.replace('_', '/')}]")
        plain_lines.append(summary)
        plain_lines.append("")
    msg.set_content("\n".join(plain_lines))
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)
    log.info("email sent to %s", recipient)
