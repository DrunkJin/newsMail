"""RSS 피드에서 카테고리별 최신 기사를 수집한다."""
from __future__ import annotations

import logging
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Iterable

import feedparser
from dateutil import parser as dateparser

# 전체 socket I/O에 timeout을 강제 — 응답 없는 RSS 서버 hang 방지.
socket.setdefaulttimeout(15)

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Article:
    source: str
    title: str
    summary: str
    link: str
    published: datetime


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return unescape(_HTML_TAG_RE.sub("", text)).strip()


def _parse_date(entry) -> datetime | None:
    for key in ("published", "updated", "pubDate"):
        val = entry.get(key)
        if not val:
            continue
        try:
            dt = dateparser.parse(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST)
        except (ValueError, TypeError):
            continue
    # struct_time fallback
    if entry.get("published_parsed"):
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)
        except (TypeError, ValueError):
            pass
    return None


def _fetch_single(source_name: str, url: str, cutoff: datetime) -> list[Article]:
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0 newsMail/1.0"})
    except Exception as e:
        log.warning("fetch failed: %s (%s) — %s", source_name, url, e)
        return []

    if feed.bozo and not feed.entries:
        log.warning("bozo feed with no entries: %s (%s)", source_name, url)
        return []

    articles: list[Article] = []
    for entry in feed.entries:
        published = _parse_date(entry)
        if published is None or published < cutoff:
            continue
        title = _clean(entry.get("title"))
        summary = _clean(entry.get("summary") or entry.get("description"))
        link = entry.get("link", "")
        if not title:
            continue
        articles.append(
            Article(
                source=source_name,
                title=title,
                summary=summary[:500],  # 토큰 절약
                link=link,
                published=published,
            )
        )
    log.info("fetched %d articles from %s", len(articles), source_name)
    return articles


def fetch_category(sources: Iterable[dict], lookback_hours: int, max_articles: int) -> list[Article]:
    cutoff = datetime.now(KST) - timedelta(hours=lookback_hours)
    all_articles: list[Article] = []

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {
            ex.submit(_fetch_single, s["name"], s["url"], cutoff): s["name"]
            for s in sources
        }
        for fut in as_completed(futures):
            all_articles.extend(fut.result())

    # 최신순 정렬, 제목 중복 제거
    all_articles.sort(key=lambda a: a.published, reverse=True)
    seen: set[str] = set()
    deduped: list[Article] = []
    for a in all_articles:
        key = re.sub(r"\s+", "", a.title)[:40]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
        if len(deduped) >= max_articles:
            break
    return deduped
