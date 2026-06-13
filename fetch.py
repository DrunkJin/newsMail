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


def _is_google_news(url: str) -> bool:
    return "news.google.com" in url


_HOSTNAME_RE = re.compile(r"^[\w-]+(\.[\w-]+)+$")


def _looks_like_hostname(s: str) -> bool:
    """`v.daum.net`, `news.naver.com` 같은 도메인 형태 판별."""
    return bool(_HOSTNAME_RE.match(s.strip()))


def _extract_google_news_source(entry, default_source: str, title: str) -> tuple[str, str]:
    """Google News entry에서 진짜 매체명을 추출하고 제목에서 접미사를 제거한다.

    Returns: (실제 매체명, 정제된 제목)
    """
    real_source = ""

    # 1순위: entry.source 요소 — 단, 도메인 형태(v.daum.net 등)면 매체명 아님으로 처리
    src_obj = entry.get("source")
    if src_obj:
        if isinstance(src_obj, dict):
            real_source = _clean(src_obj.get("title") or src_obj.get("value") or "")
        elif hasattr(src_obj, "title"):
            real_source = _clean(getattr(src_obj, "title", ""))
        elif isinstance(src_obj, str):
            real_source = _clean(src_obj)
    if real_source and _looks_like_hostname(real_source):
        real_source = ""

    # 2순위: 제목 접미사 " - 매체명" 파싱
    if not real_source:
        m = re.search(r"\s+-\s+([^-\n]+?)\s*$", title)
        if m:
            candidate = m.group(1).strip()
            # 길이 적정 + 도메인 아닌 경우만 채택
            if 0 < len(candidate) <= 30 and not _looks_like_hostname(candidate):
                real_source = candidate

    # 추출에 성공했으면 제목 끝의 " - 매체명" 접미사 제거 (dedup·표시 모두에 유리)
    if real_source:
        title = re.sub(
            r"\s+-\s+" + re.escape(real_source) + r"\s*$", "", title
        ).strip()

    return (real_source or default_source), title


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

    is_google = _is_google_news(url)
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
        article_source = source_name
        if is_google:
            article_source, title = _extract_google_news_source(entry, source_name, title)
        articles.append(
            Article(
                source=article_source,
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
